import contextlib
import io
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import convert_remote_routes
from nginx_renderer import (
    RENDERER_VERSION,
    RedirectSpec,
    RendererError,
    RouteSpec,
    normalize_origin,
    render_route,
    resolve_public_upstream_ips,
)


class OriginValidationTests(unittest.TestCase):
    def test_normalizes_https_origin(self):
        self.assertEqual(normalize_origin("  HTTPS://Example.COM/  "), "https://example.com")
        self.assertEqual(normalize_origin("https://media.example:8443"), "https://media.example:8443")

    def test_rejects_unsafe_origin_components(self):
        rejected = (
            "http://media.example",
            "https://user:password@media.example",
            "https://media.example/web",
            "https://media.example?token=secret",
            "https://media.example/#fragment",
            "https://media.example\n.evil.example",
            "file:///etc/passwd",
        )
        for value in rejected:
            with self.subTest(value=value), self.assertRaises(RendererError):
                normalize_origin(value)

    def test_http_requires_explicit_legacy_override(self):
        self.assertEqual(
            normalize_origin("http://media.example", allow_insecure_http=True),
            "http://media.example",
        )

    @mock.patch("nginx_renderer.socket.getaddrinfo")
    def test_resolver_pins_all_public_answers(self, getaddrinfo):
        getaddrinfo.return_value = [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:4700:4700::1111", 443, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443)),
        ]
        self.assertEqual(
            resolve_public_upstream_ips("media.example", 443),
            ("1.1.1.1", "2606:4700:4700::1111"),
        )

    @mock.patch("nginx_renderer.socket.getaddrinfo")
    def test_resolver_rejects_mixed_private_answer(self, getaddrinfo):
        getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ]
        with self.assertRaisesRegex(RendererError, "not globally routable"):
            resolve_public_upstream_ips("rebind.example", 443)


class RendererTests(unittest.TestCase):
    @staticmethod
    def spec(**changes):
        values = {
            "origin": "https://media.example",
            "public_host": "media.node.example.net",
            "upstream_ips": ("8.8.8.8",),
            "tls_cert_file": "/etc/unirelay/fullchain.pem",
            "tls_key_file": "/etc/unirelay/key.pem",
        }
        values.update(changes)
        return RouteSpec(**values)

    def test_secure_https_defaults(self):
        rendered = render_route(self.spec())
        self.assertIn(f"# unirelay-renderer-version: {RENDERER_VERSION}", rendered)
        self.assertIn("server 8.8.8.8:443 max_fails=2 fail_timeout=10s;", rendered)
        self.assertIn("proxy_pass https://unirelay_backend_", rendered)
        self.assertNotIn("resolver ", rendered)
        self.assertIn("proxy_ssl_verify on;", rendered)
        self.assertIn("proxy_ssl_verify_depth 5;", rendered)
        self.assertIn(
            'proxy_ssl_trusted_certificate "/etc/ssl/certs/ca-certificates.crt";',
            rendered,
        )
        self.assertIn('proxy_ssl_name "media.example";', rendered)
        self.assertIn('proxy_set_header Host "media.example";', rendered)

    def test_origin_referer_websocket_and_cookie_policy(self):
        rendered = render_route(self.spec())
        self.assertIn("map $http_origin $unirelay_origin_ok_", rendered)
        self.assertIn("if ($unirelay_origin_ok_", rendered)
        self.assertIn("= 0) { return 403; }", rendered)
        self.assertIn("map $http_referer $unirelay_referer_", rendered)
        self.assertIn('default "";', rendered)
        self.assertIn("~*^websocket$ websocket;", rendered)
        self.assertNotIn("default upgrade;", rendered)
        self.assertIn("proxy_set_header Upgrade $unirelay_upgrade_", rendered)
        self.assertIn("proxy_set_header Connection $unirelay_connection_", rendered)
        self.assertIn("proxy_cookie_domain ~(?i)^\\.?.+$ $host;", rendered)
        self.assertIn("proxy_hide_header Clear-Site-Data;", rendered)
        self.assertIn('proxy_set_header Proxy-Authorization "";', rendered)
        self.assertIn('proxy_set_header TE "";', rendered)

    def test_streaming_and_range_compatibility(self):
        rendered = render_route(self.spec())
        expected = (
            "proxy_set_header Range $http_range;",
            "proxy_set_header If-Range $http_if_range;",
            "proxy_set_header Accept-Encoding $http_accept_encoding;",
            "proxy_buffering off;",
            "proxy_request_buffering off;",
            "proxy_max_temp_file_size 0;",
            "proxy_force_ranges on;",
            "proxy_read_timeout 3600s;",
            "proxy_send_timeout 3600s;",
        )
        for directive in expected:
            with self.subTest(directive=directive):
                self.assertIn(directive, rendered)

    def test_nat_public_port_does_not_change_internal_listener(self):
        rendered = render_route(self.spec(public_https_port=12172))
        self.assertIn("https://media.node.example.net:12172", rendered)
        self.assertIn("listen 443 ssl;", rendered)
        self.assertNotIn("listen 12172 ssl;", rendered)

    def test_custom_internal_port_changes_listener_only(self):
        rendered = render_route(self.spec(public_https_port=12172, internal_https_port=8443))
        self.assertIn("https://media.node.example.net:12172", rendered)
        self.assertIn("listen 8443 ssl;", rendered)
        self.assertIn("listen [::]:8443 ssl;", rendered)
        self.assertNotIn("listen 443 ssl;", rendered)

    def test_internal_http_port_is_rejected(self):
        with self.assertRaisesRegex(RendererError, "cannot be 80"):
            render_route(self.spec(internal_https_port=80))

    def test_private_pinned_address_is_rejected(self):
        with self.assertRaisesRegex(RendererError, "not globally routable"):
            render_route(self.spec(upstream_ips=("169.254.169.254",)))

    def test_http_is_rejected_unless_explicit(self):
        with self.assertRaisesRegex(RendererError, "insecure HTTP"):
            render_route(self.spec(origin="http://media.example"))
        rendered = render_route(self.spec(
            origin="http://media.example",
            upstream_ips=("1.1.1.1",),
            allow_insecure_http=True,
        ))
        self.assertIn("proxy_pass http://unirelay_backend_", rendered)
        self.assertNotIn("proxy_ssl_verify on;", rendered)

    def test_optional_redirect_is_pinned_verified_and_credential_independent(self):
        rendered = render_route(self.spec(redirect=RedirectSpec(
            hostname="cdn.example",
            upstream_ips=("1.1.1.1",),
            token="randomRedirectToken123456789",
        )))
        self.assertIn("server 1.1.1.1:443 max_fails=2 fail_timeout=10s;", rendered)
        self.assertIn("location ^~ /_unirelay_follow_randomRedirectToken123456789/", rendered)
        self.assertIn('proxy_ssl_name "cdn.example";', rendered)
        self.assertEqual(rendered.count("proxy_ssl_verify on;"), 2)
        self.assertNotIn("ADMIN_PASSWORD", rendered)

    def test_access_log_is_off_unless_safe_traffic_log_is_requested(self):
        self.assertIn("access_log off;", render_route(self.spec()))
        rendered = render_route(self.spec(
            traffic_log_path="/var/log/unirelay-traffic.log",
            traffic_log_format="unirelay_traffic",
        ))
        self.assertIn(
            'access_log "/var/log/unirelay-traffic.log" unirelay_traffic buffer=64k flush=5s;',
            rendered,
        )


class ConverterIntegrationTests(unittest.TestCase):
    @mock.patch("convert_remote_routes.resolve_public_upstream_ips", return_value=("8.8.8.8",))
    def test_converter_uses_versioned_secure_renderer(self, _resolve):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            output = root / "output"
            source.mkdir()
            (source / "media.node.example.net.caddy").write_text(
                "# generated by uniproxy for https://media.example\n",
                encoding="utf-8",
            )
            argv = [
                "convert_remote_routes.py",
                "--source", str(source),
                "--output", str(output),
                "--suffix", "node.example.net",
                "--cert", "/etc/unirelay/fullchain.pem",
                "--key", "/etc/unirelay/key.pem",
                "--public-port", "443",
            ]
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
                convert_remote_routes.main()
            rendered = (output / "media.node.example.net.conf").read_text(encoding="utf-8")
            self.assertIn(f"# unirelay-renderer-version: {RENDERER_VERSION}", rendered)
            self.assertIn("proxy_ssl_verify on;", rendered)
            self.assertIn("server 8.8.8.8:443", rendered)
            self.assertNotIn("resolver ", rendered)


if __name__ == "__main__":
    unittest.main()
