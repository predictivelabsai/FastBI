"""mybritain-style gate: persistent guest allowance, rate limit, BYOK."""
from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.requests import Request


def _request(ip="203.0.113.7", forwarded=None) -> Request:
    headers = []
    if forwarded:
        headers.append((b"x-forwarded-for", forwarded.encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/chat/stream",
        "raw_path": b"/chat/stream",
        "query_string": b"",
        "headers": headers,
        "client": (ip, 12345),
        "server": ("test", 80),
    }
    return Request(scope)


class QuotaTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        os.environ.pop("DB_URL", None)
        import db
        import web.quota as quota

        db.DB_PATH = str(Path(self.tempdir.name) / "gate-test.sqlite")
        self.quota = importlib.reload(quota)
        self.quota._mem.clear()
        self.quota._table_ready = False
        # Force memory backend for isolation of cookie-clearing tests when needed
        self._orig_db = self.quota._db_conn

    def tearDown(self):
        self.tempdir.cleanup()

    def test_guest_allowance_survives_cookie_clearing_in_sqlite(self):
        ip = "203.0.113.7"
        self.assertTrue(all(self.quota.reserve_guest(ip) for _ in range(self.quota.FREE_QUERIES)))
        self.assertFalse(self.quota.reserve_guest(ip))
        self.assertEqual(self.quota.guest_remaining(ip), 0)
        self.assertTrue(self.quota.reserve_guest("203.0.113.8"))

    def test_refund_returns_slot(self):
        ip = "198.51.100.1"
        for _ in range(self.quota.FREE_QUERIES):
            self.quota.reserve_guest(ip)
        self.quota.refund_guest(ip)
        self.assertEqual(self.quota.guest_remaining(ip), 1)

    def test_ip_is_hashed(self):
        self.assertNotIn("203.0.113.7", self.quota.ip_hash("203.0.113.7"))


class ByokTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        import db
        import web.byok as byok

        db.DB_PATH = str(Path(self.tempdir.name) / "byok-test.sqlite")
        os.environ["FASTBI_SECRET"] = "test-secret-for-byok"
        self.byok = importlib.reload(byok)
        self.byok._key_cache.clear()
        self.byok._table_ready = False

    def tearDown(self):
        self.tempdir.cleanup()

    def test_encryption_roundtrip(self):
        f = self.byok._fernet()
        token = f.encrypt(b"xai-abc").decode()
        self.assertNotIn("xai-abc", token)
        self.assertEqual(f.decrypt(token.encode()), b"xai-abc")

    def test_key_shape(self):
        self.assertTrue(self.byok.valid_key_shape("xai-" + "a" * 30))
        self.assertFalse(self.byok.valid_key_shape("sk-123"))
        self.assertFalse(self.byok.valid_key_shape("xai-short"))

    def test_save_and_load_for_email(self):
        sess = {"user": "analyst@example.com"}
        self.byok.set_user_key(sess, "xai-" + "k" * 30)
        self.byok._key_cache.clear()
        provider, key, _model = self.byok.get_user_cred(sess)
        self.assertEqual(provider, "xai")
        self.assertEqual(key, "xai-" + "k" * 30)
        self.assertNotIn("user_xai_key", sess)

    def test_admin_allowlist(self):
        with patch.dict(os.environ, {"FASTBI_GRAPH_ADMIN_EMAILS": "kaljuvee@gmail.com"}, clear=False):
            byok = importlib.reload(self.byok)
            self.assertTrue(byok.server_key_allowed("kaljuvee@gmail.com"))
            self.assertFalse(byok.server_key_allowed("stranger@example.com"))


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        import db
        import web.quota as quota
        import web.byok as byok
        import web.ai_gate as ai_gate

        db.DB_PATH = str(Path(self.tempdir.name) / "gate-eval.sqlite")
        os.environ["FASTBI_SECRET"] = "test-secret-for-byok"
        os.environ.pop("FASTBI_GRAPH_ADMIN_EMAILS", None)
        os.environ.pop("FASTBI_ADMIN_EMAIL", None)
        os.environ.pop("FASTINSIGHTS_ADMIN_EMAIL", None)
        os.environ.pop("GOOGLE_ALLOWED_EMAILS", None)
        self.quota = importlib.reload(quota)
        self.byok = importlib.reload(byok)
        self.gate = importlib.reload(ai_gate)
        self.quota._mem.clear()
        self.quota._table_ready = False
        self.byok._key_cache.clear()
        self.byok._table_ready = False
        self.gate._RATE_LIMIT_REQUESTS.clear()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_guest_blocked_after_free_allowance(self):
        req = _request()
        sess = {}
        for _ in range(self.gate.FREE_QUERIES):
            self.assertIsNone(self.gate.evaluate(req, sess))
        blocked = self.gate.evaluate(req, sess)
        self.assertIsNotNone(blocked)
        self.assertEqual(blocked["error"], "login_required")
        self.assertEqual(blocked["status"], 402)

    def test_fourth_question_blocked_even_with_fresh_session(self):
        req = _request()
        for _ in range(self.gate.FREE_QUERIES):
            self.assertIsNone(self.gate.evaluate(req, {}))
        blocked = self.gate.evaluate(req, {})  # cleared cookies
        self.assertEqual(blocked["error"], "login_required")

    def test_signed_in_without_key_is_blocked(self):
        req = _request()
        blocked = self.gate.evaluate(req, {"user": "user@example.com"})
        self.assertEqual(blocked["error"], "api_key_required")
        self.assertEqual(blocked["status"], 402)

    def test_signed_in_admin_may_use_server_key(self):
        req = _request()
        with patch.dict(os.environ, {"FASTBI_GRAPH_ADMIN_EMAILS": "kaljuvee@gmail.com"}, clear=False):
            importlib.reload(self.byok)
            gate = importlib.reload(self.gate)
            self.assertIsNone(gate.evaluate(req, {"user": "kaljuvee@gmail.com"}))

    def test_signed_in_with_key_is_allowed(self):
        req = _request()
        sess = {"user": "analyst@example.com"}
        self.byok.set_user_key(sess, "xai-" + "k" * 30)
        self.assertIsNone(self.gate.evaluate(req, sess))
        self.assertEqual(self.byok.current_key(), "xai-" + "k" * 30)

    def test_rate_limit_blocks_anonymous_burst(self):
        req = _request("198.51.100.9")
        # Don't consume guest slots: reuse consume=False and force the limiter.
        original_anon = self.gate.RATE_LIMIT_ANON
        self.gate.RATE_LIMIT_ANON = 3
        try:
            for _ in range(3):
                self.assertFalse(self.gate.rate_limited(req, False))
            self.assertTrue(self.gate.rate_limited(req, False))
        finally:
            self.gate.RATE_LIMIT_ANON = original_anon

    def test_refund_restores_guest_cookie_counter(self):
        req = _request("203.0.113.50")
        sess = {}
        self.assertIsNone(self.gate.evaluate(req, sess))
        self.assertEqual(sess["free_q"], 1)
        self.gate.refund_if_guest(req, sess, True)
        self.assertEqual(sess["free_q"], 0)
        self.assertEqual(self.quota.guest_remaining("203.0.113.50"), self.quota.FREE_QUERIES)


class VersionChipTests(unittest.TestCase):
    def test_version_label_and_topbar_chip(self):
        from version import read_version, version_label
        from web.layout import page, main_chat

        ver, date = read_version()
        self.assertTrue(ver)
        label = version_label()
        html = "".join(str(item) for item in page(
            "ai", "FastBI", "analyst@example.com", "thread-1", main_chat("thread-1")
        ))
        self.assertIn('data-testid="app-version"', html)
        self.assertIn(label, html)


if __name__ == "__main__":
    unittest.main()
