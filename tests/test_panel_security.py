import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from origin_security import SafeOriginResolution
from panel import PanelError, ProxyPanel, SCHEMA_VERSION, USER_CSRF_COOKIE, USER_SESSION_COOKIE


class PanelSecurityIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {
            "ADMIN_USERNAME": "admin",
            "ADMIN_PASSWORD": "test-admin-password-not-for-production",
            "AGENT_TOKEN": "test-agent-token-not-for-production",
            "AUTH_THROTTLE_SECRET": "test-auth-throttle-secret-32-bytes",
            "NODE_CREDENTIAL_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            "PANEL_DB_PATH": str(root / "panel.db"),
            "PROXY_DOMAIN_SUFFIX": "sh.996878.xyz",
            "AUTO_NODE_ZONE": "996878.xyz",
            "TLS_CERT_FILE": "/tmp/test-fullchain.pem",
            "TLS_KEY_FILE": "/tmp/test-key.pem",
            "GENERATED_NGINX_DIR": str(root / "generated"),
            "NGINX_CONFIG_FILE": "/tmp/nginx.conf",
            "TRAFFIC_LOG_PATH": "/var/log/uniproxy-traffic.log",
            "USER_ORIGIN_ALLOWED_PORTS": "443",
            "MINIMUM_PASSWORD_LENGTH": "12",
        }, clear=False)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.panel = ProxyPanel(lambda value: value)
        self.panel.setup()

    def connect(self):
        connection = sqlite3.connect(self.panel.db_path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def safe_resolution(origin: str, **_kwargs) -> SafeOriginResolution:
        host = origin.split("//", 1)[-1].split(":", 1)[0].rstrip("/")
        return SafeOriginResolution(
            origin=f"https://{host}", scheme="https", hostname=host,
            port=443, authority=host, addresses=("93.184.216.34",),
        )

    def test_additive_schema_is_versioned_and_idempotent(self):
        with closing(self.connect()) as db:
            version = db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]
            route_columns = {row[1] for row in db.execute("PRAGMA table_info(routes)")}
            node_columns = {row[1] for row in db.execute("PRAGMA table_info(nodes)")}
        self.assertEqual(int(version), SCHEMA_VERSION)
        self.assertIn("resolved_ips_json", route_columns)
        self.assertIn("redirect_token", route_columns)
        self.assertIn("ssh_host_fingerprint", node_columns)
        self.panel.setup()

    def test_host_cookie_names_have_no_domain_scope(self):
        response = web.Response()
        self.panel._set_user_session(response, "a" * 43, "b" * 43)
        session = response.cookies[USER_SESSION_COOKIE]
        csrf = response.cookies[USER_CSRF_COOKIE]
        self.assertTrue(USER_SESSION_COOKIE.startswith("__Host-"))
        self.assertTrue(USER_CSRF_COOKIE.startswith("__Host-"))
        self.assertTrue(session["secure"])
        self.assertTrue(session["httponly"])
        self.assertEqual(session["path"], "/")
        self.assertFalse(session["domain"])
        self.assertTrue(csrf["secure"])
        self.assertFalse(csrf["domain"])

    def test_control_plane_origin_is_exact_not_same_site(self):
        valid = make_mocked_request("POST", "/login", headers={"Origin": "https://sh.996878.xyz"})
        self.panel._check_request_origin(valid)
        default_port = make_mocked_request("POST", "/login", headers={"Origin": "https://sh.996878.xyz:443"})
        self.panel._check_request_origin(default_port)
        same_host_port = make_mocked_request("POST", "/login", headers={"Origin": "https://sh.996878.xyz:8443"})
        self.panel._check_request_origin(same_host_port, allow_missing=True)
        same_host_http = make_mocked_request("POST", "/login", headers={"Origin": "http://sh.996878.xyz"})
        self.panel._check_request_origin(same_host_http, allow_missing=True)
        referer_fallback = make_mocked_request(
            "POST", "/login", headers={"Referer": "https://sh.996878.xyz/_admin/nodes"}
        )
        self.panel._check_request_origin(referer_fallback)
        sibling = make_mocked_request("POST", "/login", headers={"Origin": "https://evil.996878.xyz"})
        with self.assertRaises(web.HTTPForbidden):
            self.panel._check_request_origin(sibling)
        missing = make_mocked_request("POST", "/login")
        with self.assertRaises(web.HTTPForbidden):
            self.panel._check_request_origin(missing)
        self.panel._check_request_origin(missing, allow_missing=True)
        invalid_with_valid_referer = make_mocked_request(
            "POST", "/login",
            headers={"Origin": "https://evil.example", "Referer": "https://sh.996878.xyz/_admin/nodes"},
        )
        with self.assertRaises(web.HTTPForbidden):
            self.panel._check_request_origin(invalid_with_valid_referer, allow_missing=True)

    def test_remote_ssh_uses_tofu_and_rejects_changed_keys(self):
        node = {
            "kind": "ssh", "ssh_host": "198.51.100.10", "ssh_port": 22,
            "ssh_user": "root", "ssh_identity": "", "ssh_password": "secret",
            "ssh_host_fingerprint": "", "ssh_password_ciphertext": "",
        }
        args = self.panel._ssh_args(node)
        self.assertIn("StrictHostKeyChecking=accept-new", args)

    def test_route_quota_check_and_insert_are_atomic(self):
        with closing(self.connect()) as db:
            created = "2026-01-01T00:00:00+00:00"
            cursor = db.execute(
                "INSERT INTO users (username,username_norm,password_hash,status,route_quota,notes,created_at,updated_at) "
                "VALUES ('alice','alice','unused','active',1,'',?,?)",
                (created, created),
            )
            user_id = cursor.lastrowid
            node_id = db.execute("SELECT id FROM nodes WHERE kind='local'").fetchone()[0]
            db.commit()
        self.panel._resolve_route_origin = self.safe_resolution
        self.panel._deploy_and_verify = lambda _node, _route: 200

        def create(index: int) -> bool:
            try:
                self.panel.create_frontend_route(
                    f"https://media-{index}.example.com", node_id, user_id
                )
                return True
            except PanelError:
                return False

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(create, range(12)))
        with closing(self.connect()) as db:
            count = db.execute(
                "SELECT COUNT(*) FROM routes WHERE owner_user_id=?", (user_id,)
            ).fetchone()[0]
        self.assertEqual(sum(results), 1)
        self.assertEqual(count, 1)

    def test_panel_renderer_uses_pinned_tls_verified_upstream(self):
        self.panel._resolve_route_origin = self.safe_resolution
        with closing(self.connect()) as db:
            node = db.execute("SELECT * FROM nodes WHERE kind='local'").fetchone()
            created = "2026-01-01T00:00:00+00:00"
            cursor = db.execute(
                "INSERT INTO routes (node_id,name,origin,public_host,deployed,state,redirect_token,created_at,updated_at) "
                "VALUES (?,'media','https://media.example.com','media.sh.996878.xyz',0,'pending',?,?,?)",
                (node["id"], "independent-random-route-token", created, created),
            )
            route = db.execute("SELECT * FROM routes WHERE id=?", (cursor.lastrowid,)).fetchone()
            db.commit()
        content = self.panel._render_mapping(route, node)
        self.assertIn("proxy_ssl_verify on;", content)
        self.assertIn("server 93.184.216.34:443", content)
        self.assertIn("proxy_cookie_domain", content)
        self.assertNotIn("resolver 1.1.1.1", content)
        self.assertNotIn(self.panel.password, content)


if __name__ == "__main__":
    unittest.main()
