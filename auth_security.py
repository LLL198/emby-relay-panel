"""Reusable authentication security primitives for emby-relay-panel.

This module intentionally has no dependency on aiohttp or the panel code.  It
contains the stateful rate limiter, password policy, and the global work gate
needed to put expensive password hashing behind a small concurrency limit.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import math
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, TypeVar


SCOPE_IP = "ip"
SCOPE_USERNAME = "username"
SCOPE_PAIR = "pair"
AUTH_SCOPES = (SCOPE_IP, SCOPE_USERNAME, SCOPE_PAIR)


@dataclass(frozen=True)
class ThrottleRule:
    """Failure window and block duration for one authentication bucket."""

    max_failures: int = 8
    window_seconds: int = 10 * 60
    block_seconds: int = 10 * 60

    def __post_init__(self) -> None:
        if self.max_failures < 1:
            raise ValueError("max_failures must be positive")
        if self.window_seconds < 1:
            raise ValueError("window_seconds must be positive")
        if self.block_seconds < 1:
            raise ValueError("block_seconds must be positive")


@dataclass(frozen=True)
class AuthThrottleConfig:
    """Configuration for the three persistent authentication limits."""

    ip: ThrottleRule = field(default_factory=ThrottleRule)
    username: ThrottleRule = field(default_factory=ThrottleRule)
    pair: ThrottleRule = field(default_factory=ThrottleRule)
    max_rows: int = 4096
    capacity_retry_seconds: int = 60
    sqlite_timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.max_rows < len(AUTH_SCOPES):
            raise ValueError("max_rows must allow at least one three-scope identity")
        if self.capacity_retry_seconds < 1:
            raise ValueError("capacity_retry_seconds must be positive")
        if self.sqlite_timeout_seconds <= 0:
            raise ValueError("sqlite_timeout_seconds must be positive")

    def rule_for(self, scope: str) -> ThrottleRule:
        if scope == SCOPE_IP:
            return self.ip
        if scope == SCOPE_USERNAME:
            return self.username
        if scope == SCOPE_PAIR:
            return self.pair
        raise ValueError(f"unknown throttle scope: {scope}")


@dataclass(frozen=True)
class ThrottleDecision:
    """Result returned before or after an authentication attempt."""

    allowed: bool
    retry_after: int = 0
    blocked_scopes: tuple[str, ...] = ()


class AuthenticationThrottled(RuntimeError):
    """Raised by callers that choose exception-based throttle handling."""

    def __init__(self, decision: ThrottleDecision):
        self.decision = decision
        super().__init__(f"authentication throttled for {decision.retry_after} seconds")


class PersistentAuthThrottle:
    """SQLite-backed three-layer authentication failure limiter.

    Bucket identifiers are HMAC-SHA256 digests.  Raw IP addresses and
    usernames are never written to the throttle table.  Call ``precheck``
    before any password hashing, then call either ``record_failure`` or
    ``record_success``.  Success deliberately clears only the exact IP/user
    pair; it never clears the IP-wide or username-wide defensive history.
    """

    def __init__(
        self,
        db_path: str | Path,
        hmac_secret: str | bytes,
        config: AuthThrottleConfig | None = None,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.db_path = str(db_path)
        self.config = config or AuthThrottleConfig()
        self.clock = clock
        if isinstance(hmac_secret, str):
            secret = hmac_secret.encode("utf-8")
        else:
            secret = bytes(hmac_secret)
        if len(secret) < 16:
            raise ValueError("hmac_secret must contain at least 16 bytes")
        self._secret = secret
        self.setup()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=self.config.sqlite_timeout_seconds)
        db.row_factory = sqlite3.Row
        db.execute(f"PRAGMA busy_timeout={int(self.config.sqlite_timeout_seconds * 1000)}")
        return db

    def setup(self) -> None:
        """Create the additive, idempotent limiter schema."""

        with closing(self._connect()) as db, db:
            db.executescript(
                "CREATE TABLE IF NOT EXISTS auth_throttles ("
                "bucket_hash TEXT PRIMARY KEY, "
                "scope TEXT NOT NULL CHECK(scope IN ('ip','username','pair')), "
                "failures INTEGER NOT NULL DEFAULT 0, "
                "window_started REAL NOT NULL, "
                "last_failed REAL NOT NULL, "
                "blocked_until REAL NOT NULL DEFAULT 0, "
                "updated_at REAL NOT NULL);"
                "CREATE INDEX IF NOT EXISTS auth_throttles_updated_at_index "
                "ON auth_throttles(updated_at);"
            )

    @staticmethod
    def _canonical_ip(client_ip: str) -> str:
        raw = str(client_ip).strip()
        try:
            return str(ipaddress.ip_address(raw))
        except ValueError:
            return (raw.lower() or "unknown")[:256]

    @staticmethod
    def _canonical_username(username: str) -> str:
        return str(username).strip().lower()[:1024]

    def _digest(self, scope: str, *components: str) -> str:
        material = json.dumps(
            [scope, *components], ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        return hmac.new(self._secret, material, hashlib.sha256).hexdigest()

    def _buckets(self, client_ip: str, username: str) -> dict[str, str]:
        canonical_ip = self._canonical_ip(client_ip)
        canonical_username = self._canonical_username(username)
        return {
            SCOPE_IP: self._digest(SCOPE_IP, canonical_ip),
            SCOPE_USERNAME: self._digest(SCOPE_USERNAME, canonical_username),
            SCOPE_PAIR: self._digest(SCOPE_PAIR, canonical_ip, canonical_username),
        }

    @staticmethod
    def _now(value: float | None, clock: Callable[[], float]) -> float:
        return float(clock() if value is None else value)

    def _cleanup_locked(self, db: sqlite3.Connection, current: float) -> int:
        deleted = 0
        for scope in AUTH_SCOPES:
            rule = self.config.rule_for(scope)
            deleted += db.execute(
                "DELETE FROM auth_throttles "
                "WHERE scope=? AND blocked_until<=? AND window_started+?<=?",
                (scope, current, rule.window_seconds, current),
            ).rowcount
        return deleted

    def cleanup(self, *, now: float | None = None) -> int:
        """Delete expired, non-blocked buckets and return the row count."""

        current = self._now(now, self.clock)
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            return self._cleanup_locked(db, current)

    @staticmethod
    def _rows_for(
        db: sqlite3.Connection, buckets: dict[str, str]
    ) -> dict[str, sqlite3.Row]:
        placeholders = ",".join("?" for _ in buckets)
        rows = db.execute(
            f"SELECT * FROM auth_throttles WHERE bucket_hash IN ({placeholders})",
            tuple(buckets.values()),
        ).fetchall()
        return {str(row["scope"]): row for row in rows}

    def _decision_for_rows(
        self, rows: dict[str, sqlite3.Row], current: float
    ) -> ThrottleDecision:
        blocked: list[str] = []
        retry_until = current
        for scope in AUTH_SCOPES:
            row = rows.get(scope)
            if row is None:
                continue
            blocked_until = float(row["blocked_until"])
            if blocked_until > current:
                blocked.append(scope)
                retry_until = max(retry_until, blocked_until)
        if not blocked:
            return ThrottleDecision(True)
        return ThrottleDecision(
            False,
            max(1, math.ceil(retry_until - current)),
            tuple(blocked),
        )

    def precheck(
        self, client_ip: str, username: str, *, now: float | None = None
    ) -> ThrottleDecision:
        """Check all limits before doing any password work.

        If the bounded table is full and this identity needs a new bucket, the
        limiter fails closed instead of evicting active defensive state.
        """

        current = self._now(now, self.clock)
        buckets = self._buckets(client_ip, username)
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            self._cleanup_locked(db, current)
            rows = self._rows_for(db, buckets)
            decision = self._decision_for_rows(rows, current)
            if not decision.allowed:
                return decision
            missing = len(buckets) - len(rows)
            if missing:
                count = int(db.execute("SELECT COUNT(*) FROM auth_throttles").fetchone()[0])
                if count + missing > self.config.max_rows:
                    return ThrottleDecision(
                        False,
                        self.config.capacity_retry_seconds,
                        ("capacity",),
                    )
        return ThrottleDecision(True)

    def require_allowed(
        self, client_ip: str, username: str, *, now: float | None = None
    ) -> None:
        decision = self.precheck(client_ip, username, now=now)
        if not decision.allowed:
            raise AuthenticationThrottled(decision)

    def record_failure(
        self, client_ip: str, username: str, *, now: float | None = None
    ) -> ThrottleDecision:
        """Atomically add a failure to the IP, username, and pair buckets."""

        current = self._now(now, self.clock)
        buckets = self._buckets(client_ip, username)
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            self._cleanup_locked(db, current)
            rows = self._rows_for(db, buckets)
            row_count = int(db.execute("SELECT COUNT(*) FROM auth_throttles").fetchone()[0])

            for scope in AUTH_SCOPES:
                rule = self.config.rule_for(scope)
                row = rows.get(scope)
                if row is None:
                    if row_count >= self.config.max_rows:
                        continue
                    failures = 1
                    window_started = current
                    blocked_until = (
                        current + rule.block_seconds
                        if failures >= rule.max_failures
                        else 0.0
                    )
                    db.execute(
                        "INSERT INTO auth_throttles "
                        "(bucket_hash,scope,failures,window_started,last_failed,blocked_until,updated_at) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (
                            buckets[scope],
                            scope,
                            failures,
                            window_started,
                            current,
                            blocked_until,
                            current,
                        ),
                    )
                    row_count += 1
                    continue

                window_started = float(row["window_started"])
                blocked_until = float(row["blocked_until"])
                if blocked_until <= current and window_started + rule.window_seconds <= current:
                    failures = 1
                    window_started = current
                else:
                    failures = int(row["failures"]) + 1
                if failures >= rule.max_failures:
                    blocked_until = max(blocked_until, current + rule.block_seconds)
                db.execute(
                    "UPDATE auth_throttles SET failures=?,window_started=?,last_failed=?,"
                    "blocked_until=?,updated_at=? WHERE bucket_hash=?",
                    (
                        failures,
                        window_started,
                        current,
                        blocked_until,
                        current,
                        buckets[scope],
                    ),
                )

            rows = self._rows_for(db, buckets)
            decision = self._decision_for_rows(rows, current)
            if len(rows) < len(buckets):
                return ThrottleDecision(
                    False,
                    max(decision.retry_after, self.config.capacity_retry_seconds),
                    tuple(dict.fromkeys((*decision.blocked_scopes, "capacity"))),
                )
            return decision

    def record_success(self, client_ip: str, username: str) -> None:
        """Clear only the exact pair bucket after successful authentication."""

        pair_hash = self._buckets(client_ip, username)[SCOPE_PAIR]
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "DELETE FROM auth_throttles WHERE bucket_hash=? AND scope=?",
                (pair_hash, SCOPE_PAIR),
            )

    def table_size(self) -> int:
        with closing(self._connect()) as db, db:
            return int(db.execute("SELECT COUNT(*) FROM auth_throttles").fetchone()[0])


DEFAULT_COMMON_PASSWORDS = frozenset(
    {
        "123456",
        "12345678",
        "123456789",
        "admin",
        "letmein",
        "password",
        "qwerty",
    }
)


@dataclass(frozen=True)
class PasswordPolicy:
    """Configurable, hash-independent password validation policy."""

    min_characters: int = 12
    max_bytes: int = 256
    common_passwords: frozenset[str] = DEFAULT_COMMON_PASSWORDS
    reject_username_match: bool = True
    reject_whitespace_only: bool = True

    def __post_init__(self) -> None:
        if self.min_characters < 1:
            raise ValueError("min_characters must be positive")
        if self.max_bytes < self.min_characters:
            raise ValueError("max_bytes must not be smaller than min_characters")
        object.__setattr__(
            self,
            "common_passwords",
            frozenset(str(value).casefold() for value in self.common_passwords),
        )

    def violations(self, password: str, *, username: str = "") -> tuple[str, ...]:
        value = str(password)
        problems: list[str] = []
        if not value:
            problems.append("empty")
        if len(value) < self.min_characters:
            problems.append("too_short")
        if len(value.encode("utf-8")) > self.max_bytes:
            problems.append("too_long")
        if self.reject_whitespace_only and value and value.isspace():
            problems.append("whitespace_only")
        normalized = value.casefold()
        if normalized in self.common_passwords:
            problems.append("common_password")
        if (
            self.reject_username_match
            and username
            and normalized == str(username).strip().casefold()
        ):
            problems.append("matches_username")
        return tuple(problems)

    def accepts(self, password: str, *, username: str = "") -> bool:
        return not self.violations(password, username=username)

    def require(self, password: str, *, username: str = "") -> None:
        problems = self.violations(password, username=username)
        if problems:
            raise PasswordPolicyViolation(problems)


class PasswordPolicyViolation(ValueError):
    def __init__(self, violations: Iterable[str]):
        self.violations = tuple(violations)
        super().__init__("password policy violation: " + ", ".join(self.violations))


class HashWorkLimitExceeded(RuntimeError):
    """Raised when password work cannot enter the bounded queue in time."""


T = TypeVar("T")


class HashWorkLimiter:
    """One shared asynchronous gate for all expensive synchronous hash work."""

    def __init__(
        self,
        max_concurrent: int = 2,
        *,
        acquire_timeout: float | None = 2.0,
        max_waiters: int = 64,
    ) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be positive")
        if acquire_timeout is not None and acquire_timeout <= 0:
            raise ValueError("acquire_timeout must be positive or None")
        if max_waiters < 0:
            raise ValueError("max_waiters must be non-negative")
        self.max_concurrent = max_concurrent
        self.acquire_timeout = acquire_timeout
        self.max_waiters = max_waiters
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._inflight = 0

    async def _enter_queue(self) -> None:
        # This check and increment contain no await, so they are atomic with
        # respect to other tasks on the limiter's event loop.  Counting active
        # and reserved work together avoids a race before Semaphore.acquire().
        if self._inflight >= self.max_concurrent + self.max_waiters:
            raise HashWorkLimitExceeded("password hash queue is full")
        self._inflight += 1
        try:
            if self.acquire_timeout is None:
                await self._semaphore.acquire()
            else:
                await asyncio.wait_for(
                    self._semaphore.acquire(), timeout=self.acquire_timeout
                )
        except TimeoutError as exc:
            self._inflight -= 1
            raise HashWorkLimitExceeded("password hash queue timed out") from exc
        except BaseException:
            self._inflight -= 1
            raise

    def _release_slot(self) -> None:
        self._semaphore.release()
        self._inflight -= 1

    async def run(self, function: Callable[..., T], /, *args, **kwargs) -> T:
        """Run one synchronous hash/check function in the bounded thread gate."""

        await self._enter_queue()
        work: asyncio.Task[T] | None = None
        release_on_exit = True
        try:
            work = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
            return await asyncio.shield(work)
        except asyncio.CancelledError:
            if work is not None and not work.done():
                work.add_done_callback(lambda _finished: self._release_slot())
                release_on_exit = False
            raise
        finally:
            if release_on_exit:
                self._release_slot()
