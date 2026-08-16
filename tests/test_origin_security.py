import ipaddress
import socket
import unittest

from origin_security import (
    OriginSecurityError,
    OriginSecurityPolicy,
    is_global_unicast,
    resolve_origin_safely,
    validate_resolved_addresses,
)


class FakeResolver:
    def __init__(self, answers=(), error=None):
        self.answers = tuple(answers)
        self.error = error
        self.calls = []

    def __call__(self, hostname):
        self.calls.append(hostname)
        if self.error is not None:
            raise self.error
        return self.answers


class OriginSecurityTests(unittest.TestCase):
    def assertSecurityCode(self, code, callback):
        with self.assertRaises(OriginSecurityError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def test_public_a_and_aaaa_are_deduplicated_and_sorted(self):
        resolver = FakeResolver([
            "2606:4700:4700::1111",
            "8.8.8.8",
            "1.1.1.1",
            "8.8.8.8",
        ])
        result = resolve_origin_safely(
            "https://Media.Example:8443/",
            resolver=resolver,
        )

        self.assertEqual(resolver.calls, ["media.example"])
        self.assertEqual(result.origin, "https://media.example:8443")
        self.assertEqual(result.authority, "media.example:8443")
        self.assertEqual(
            result.addresses,
            ("1.1.1.1", "8.8.8.8", "2606:4700:4700::1111"),
        )
        self.assertEqual(
            result.upstream_endpoints,
            ("1.1.1.1:8443", "8.8.8.8:8443", "[2606:4700:4700::1111]:8443"),
        )
        self.assertEqual(result.renderer_context()["tls_server_name"], "media.example")

    def test_default_policy_rejects_http_but_can_be_explicitly_enabled(self):
        resolver = FakeResolver(["1.1.1.1"])
        self.assertSecurityCode(
            "scheme-not-allowed",
            lambda: resolve_origin_safely("http://media.example", resolver=resolver),
        )

        policy = OriginSecurityPolicy(allowed_schemes=("http", "https"))
        result = resolve_origin_safely("http://media.example", policy=policy, resolver=resolver)
        self.assertEqual(result.origin, "http://media.example")
        self.assertEqual(result.port, 80)

    def test_non_global_answers_are_rejected(self):
        unsafe = (
            "0.0.0.0",
            "10.0.0.1",
            "100.64.0.1",
            "127.0.0.1",
            "169.254.169.254",
            "172.16.0.1",
            "192.0.0.8",
            "192.0.2.1",
            "192.88.99.1",
            "192.168.1.1",
            "198.18.0.1",
            "198.51.100.1",
            "203.0.113.1",
            "224.0.0.1",
            "255.255.255.255",
            "::",
            "::1",
            "::ffff:8.8.8.8",
            "64:ff9b::808:808",
            "64:ff9b:1::1",
            "100::1",
            "2001::1",
            "2001:db8::1",
            "3fff::1",
            "fc00::1",
            "fe80::1",
            "ff02::1",
        )
        for address in unsafe:
            with self.subTest(address=address):
                self.assertFalse(is_global_unicast(address))
                self.assertSecurityCode(
                    "non-global-address",
                    lambda address=address: resolve_origin_safely(
                        "https://media.example",
                        resolver=FakeResolver([address]),
                    ),
                )

    def test_mixed_public_and_private_answer_rejects_whole_set(self):
        resolver = FakeResolver(["1.1.1.1", "169.254.169.254"])
        self.assertSecurityCode(
            "mixed-address-space",
            lambda: resolve_origin_safely("https://rebind.example", resolver=resolver),
        )

    def test_owned_domain_and_subdomain_are_rejected_before_dns(self):
        resolver = FakeResolver(["1.1.1.1"])
        policy = OriginSecurityPolicy(
            owned_domains=("996878.xyz",),
            protected_hosts=("relay.example.net",),
        )
        for origin in (
            "https://996878.xyz",
            "https://n-node.996878.xyz",
            "https://relay.example.net",
        ):
            with self.subTest(origin=origin):
                self.assertSecurityCode(
                    "owned-origin",
                    lambda origin=origin: resolve_origin_safely(origin, policy=policy, resolver=resolver),
                )
        self.assertEqual(resolver.calls, [])

    def test_domain_suffix_lookalike_is_not_treated_as_owned(self):
        resolver = FakeResolver(["1.1.1.1"])
        policy = OriginSecurityPolicy(owned_domains=("996878.xyz",))
        result = resolve_origin_safely(
            "https://not996878.xyz",
            policy=policy,
            resolver=resolver,
        )
        self.assertEqual(result.addresses, ("1.1.1.1",))

    def test_node_and_proxy_addresses_are_rejected_even_through_alias(self):
        policy = OriginSecurityPolicy(
            node_addresses=("8.8.8.8",),
            proxy_addresses=("2606:4700:4700::1111",),
        )
        for address in ("8.8.8.8", "2606:4700:4700::1111"):
            with self.subTest(address=address):
                self.assertSecurityCode(
                    "proxy-loop",
                    lambda address=address: resolve_origin_safely(
                        "https://alias.example",
                        policy=policy,
                        resolver=FakeResolver([address]),
                    ),
                )

    def test_public_literal_skips_dns_and_private_literal_fails(self):
        resolver = FakeResolver(error=AssertionError("literal must not resolve"))
        result = resolve_origin_safely("https://[2606:4700:4700::1111]:9443", resolver=resolver)
        self.assertEqual(result.origin, "https://[2606:4700:4700::1111]:9443")
        self.assertEqual(result.upstream_endpoints, ("[2606:4700:4700::1111]:9443",))
        self.assertEqual(resolver.calls, [])

        self.assertSecurityCode(
            "non-global-address",
            lambda: resolve_origin_safely("https://127.0.0.1", resolver=resolver),
        )

    def test_empty_invalid_and_excessive_answer_sets_fail_closed(self):
        self.assertSecurityCode(
            "no-addresses",
            lambda: resolve_origin_safely("https://empty.example", resolver=FakeResolver([])),
        )
        self.assertSecurityCode(
            "invalid-address",
            lambda: resolve_origin_safely("https://bad.example", resolver=FakeResolver(["not-an-ip"])),
        )
        policy = OriginSecurityPolicy(max_addresses=2, max_resolver_answers=3)
        self.assertSecurityCode(
            "too-many-addresses",
            lambda: validate_resolved_addresses(
                "many.example",
                ["1.1.1.1", "8.8.8.8", "9.9.9.9"],
                policy,
            ),
        )
        self.assertSecurityCode(
            "too-many-answers",
            lambda: validate_resolved_addresses(
                "duplicate.example",
                ["1.1.1.1", "1.1.1.1", "1.1.1.1", "1.1.1.1"],
                policy,
            ),
        )

    def test_resolver_errors_are_normalised(self):
        self.assertSecurityCode(
            "resolution-failed",
            lambda: resolve_origin_safely(
                "https://missing.example",
                resolver=FakeResolver(error=socket.gaierror("missing")),
            ),
        )

    def test_origin_components_and_credentials_are_rejected(self):
        resolver = FakeResolver(["1.1.1.1"])
        cases = {
            "https://user:pass@media.example": "userinfo-not-allowed",
            "https://media.example/web": "origin-components-not-allowed",
            "https://media.example?x=1": "origin-components-not-allowed",
            "https://media.example#x": "origin-components-not-allowed",
            "https://media.example:0": "invalid-origin",
            "https://media.example:99999": "invalid-origin",
            "ftp://media.example": "scheme-not-allowed",
        }
        for origin, code in cases.items():
            with self.subTest(origin=origin):
                self.assertSecurityCode(
                    code,
                    lambda origin=origin: resolve_origin_safely(origin, resolver=resolver),
                )

    def test_policy_input_is_normalised_and_validated(self):
        policy = OriginSecurityPolicy(
            owned_domains=("EXAMPLE.COM.",),
            node_addresses=(ipaddress.ip_address("8.8.8.8"),),
            allowed_schemes=("HTTPS", "https"),
        )
        self.assertEqual(policy.owned_domains, ("example.com",))
        self.assertEqual(policy.node_addresses, ("8.8.8.8",))
        self.assertEqual(policy.allowed_schemes, ("https",))
        with self.assertRaises(ValueError):
            OriginSecurityPolicy(owned_domains=("127.0.0.1",))

    def test_known_public_unicast_addresses_are_allowed(self):
        for address in ("1.1.1.1", "8.8.8.8", "2606:4700:4700::1111"):
            with self.subTest(address=address):
                self.assertTrue(is_global_unicast(address))


if __name__ == "__main__":
    unittest.main()
