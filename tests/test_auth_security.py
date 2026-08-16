import asyncio
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path

from auth_security import (
    AuthThrottleConfig,
    HashWorkLimitExceeded,
    HashWorkLimiter,
    PasswordPolicy,
    PasswordPolicyViolation,
    PersistentAuthThrottle,
    ThrottleRule,
)


TEST_SECRET = b"test-only-auth-throttle-secret-32b"


def test_config(
    *,
    ip_limit=2,
    username_limit=2,
    pair_limit=2,
    window=60,
    block=60,
    max_rows=128,
):
    return AuthThrottleConfig(
        ip=ThrottleRule(ip_limit, window, block),
        username=ThrottleRule(username_limit, window, block),
        pair=ThrottleRule(pair_limit, window, block),
        max_rows=max_rows,
        capacity_retry_seconds=7,
    )


class PersistentAuthThrottleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.db_path = Path(self.temporary.name) / "panel.db"

    def limiter(self, config=None):
        return PersistentAuthThrottle(
            self.db_path,
            TEST_SECRET,
            config or test_config(),
        )

    def test_lock_survives_process_restart(self):
        first = self.limiter()
        self.assertTrue(first.precheck("203.0.113.7", "Alice", now=100).allowed)
        first.record_failure("203.0.113.7", "Alice", now=100)
        first.record_failure("203.0.113.7", "Alice", now=101)

        restarted = self.limiter()
        decision = restarted.precheck("203.0.113.7", "alice", now=102)

        self.assertFalse(decision.allowed)
        self.assertGreaterEqual(decision.retry_after, 59)
        self.assertEqual(set(decision.blocked_scopes), {"ip", "username", "pair"})

    def test_precheck_blocks_correct_password_before_it_is_evaluated(self):
        limiter = self.limiter()
        password_checks = 0

        def authenticate(candidate):
            nonlocal password_checks
            decision = limiter.precheck("203.0.113.8", "bob", now=103)
            if not decision.allowed:
                return False
            password_checks += 1
            return candidate == "correct"

        limiter.record_failure("203.0.113.8", "bob", now=100)
        limiter.record_failure("203.0.113.8", "bob", now=101)

        self.assertFalse(authenticate("correct"))
        self.assertEqual(password_checks, 0)

    def test_success_does_not_clear_ip_or_username_history(self):
        config = test_config(ip_limit=2, username_limit=2, pair_limit=2)
        limiter = self.limiter(config)
        limiter.record_failure("203.0.113.9", "carol", now=100)
        limiter.record_failure("203.0.113.9", "carol", now=101)

        limiter.record_success("203.0.113.9", "carol")

        original = limiter.precheck("203.0.113.9", "carol", now=102)
        different_user = limiter.precheck("203.0.113.9", "dave", now=102)
        self.assertFalse(original.allowed)
        self.assertIn("ip", original.blocked_scopes)
        self.assertIn("username", original.blocked_scopes)
        self.assertNotIn("pair", original.blocked_scopes)
        self.assertFalse(different_user.allowed)
        self.assertEqual(different_user.blocked_scopes, ("ip",))

    def test_expired_rows_are_cleaned_and_identity_can_retry(self):
        limiter = self.limiter(test_config(ip_limit=1, username_limit=1, pair_limit=1))
        limiter.record_failure("203.0.113.10", "erin", now=100)
        self.assertEqual(limiter.table_size(), 3)

        deleted = limiter.cleanup(now=161)

        self.assertEqual(deleted, 3)
        self.assertEqual(limiter.table_size(), 0)
        self.assertTrue(limiter.precheck("203.0.113.10", "erin", now=161).allowed)

    def test_table_contains_only_hmac_bucket_identifiers(self):
        limiter = self.limiter()
        limiter.record_failure("203.0.113.11", "VisibleName", now=100)

        with closing(sqlite3.connect(self.db_path)) as db:
            rows = db.execute(
                "SELECT bucket_hash,scope FROM auth_throttles ORDER BY scope"
            ).fetchall()

        self.assertEqual(len(rows), 3)
        for bucket_hash, scope in rows:
            self.assertEqual(len(bucket_hash), 64)
            int(bucket_hash, 16)
            self.assertNotIn("203.0.113.11", bucket_hash)
            self.assertNotIn("visiblename", bucket_hash)
            self.assertIn(scope, {"ip", "username", "pair"})

    def test_table_limit_fails_closed_without_exceeding_cap(self):
        limiter = self.limiter(test_config(max_rows=3))
        limiter.record_failure("203.0.113.12", "first", now=100)
        self.assertEqual(limiter.table_size(), 3)

        decision = limiter.precheck("203.0.113.13", "second", now=101)
        recorded = limiter.record_failure("203.0.113.13", "second", now=101)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.blocked_scopes, ("capacity",))
        self.assertFalse(recorded.allowed)
        self.assertIn("capacity", recorded.blocked_scopes)
        self.assertEqual(limiter.table_size(), 3)


class PasswordPolicyTests(unittest.TestCase):
    def test_configurable_policy_reports_stable_violation_codes(self):
        policy = PasswordPolicy(
            min_characters=8,
            max_bytes=32,
            common_passwords=frozenset({"known-bad"}),
        )

        self.assertIn("too_short", policy.violations("short", username="alice"))
        self.assertIn("matches_username", policy.violations("alice", username="ALICE"))
        self.assertIn("common_password", policy.violations("KNOWN-BAD"))
        self.assertIn("too_long", policy.violations("界" * 11))
        self.assertTrue(policy.accepts("correct horse", username="alice"))

    def test_require_raises_with_machine_readable_reasons(self):
        policy = PasswordPolicy(min_characters=8, max_bytes=32)
        with self.assertRaises(PasswordPolicyViolation) as caught:
            policy.require("admin", username="admin")
        self.assertIn("matches_username", caught.exception.violations)
        self.assertIn("common_password", caught.exception.violations)


class HashWorkLimiterTests(unittest.IsolatedAsyncioTestCase):
    async def test_hash_work_never_exceeds_global_concurrency(self):
        limiter = HashWorkLimiter(max_concurrent=2, acquire_timeout=2, max_waiters=8)
        lock = threading.Lock()
        active = 0
        peak = 0

        def work(value):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.04)
            with lock:
                active -= 1
            return value * 2

        results = await asyncio.gather(*(limiter.run(work, index) for index in range(6)))

        self.assertEqual(results, [0, 2, 4, 6, 8, 10])
        self.assertEqual(peak, 2)

    async def test_full_hash_queue_fails_fast(self):
        limiter = HashWorkLimiter(
            max_concurrent=1,
            acquire_timeout=1,
            max_waiters=0,
        )
        started = threading.Event()
        release = threading.Event()

        def blocking_work():
            started.set()
            release.wait(timeout=2)

        first = asyncio.create_task(limiter.run(blocking_work))
        await asyncio.to_thread(started.wait, 1)
        with self.assertRaises(HashWorkLimitExceeded):
            await limiter.run(lambda: None)
        release.set()
        await first


if __name__ == "__main__":
    unittest.main()
