"""
Tests for app/auth.py's bearer-token dependency and its wiring in
app/main.py (security hardening).
"""

import pytest

from app.auth import _MIN_TOKEN_LENGTH, _configured_token, _matches


def test_no_token_rejects_everything(monkeypatch):
    monkeypatch.delenv("APP_ACCESS_TOKEN", raising=False)
    assert _configured_token() is None
    assert _matches("anything") is False


def test_short_token_fails_closed(monkeypatch):
    monkeypatch.setenv("APP_ACCESS_TOKEN", "short")
    assert len("short") < _MIN_TOKEN_LENGTH
    assert _configured_token() is None
    assert _matches("short") is False


def test_correct_token_matches(monkeypatch):
    token = "a" * 40
    monkeypatch.setenv("APP_ACCESS_TOKEN", token)
    assert _matches(token) is True


def test_wrong_token_does_not_match(monkeypatch):
    monkeypatch.setenv("APP_ACCESS_TOKEN", "a" * 40)
    assert _matches("b" * 40) is False


class TestProtectedRoutes:
    def test_candidates_without_token_is_401(self, client):
        res = client.get("/candidates")
        assert res.status_code == 401

    def test_candidates_with_wrong_token_is_401(self, client):
        res = client.get("/candidates", headers={"Authorization": "Bearer wrong-token-wrong-token"})
        assert res.status_code == 401

    def test_candidates_with_correct_token_is_200(self, client, auth_headers):
        res = client.get("/candidates", headers=auth_headers)
        assert res.status_code == 200

    def test_scan_requires_token(self, client):
        assert client.post("/scan").status_code == 401

    def test_extract_requires_token(self, client):
        assert client.post("/extract").status_code == 401

    def test_scheduler_status_requires_token(self, client):
        assert client.get("/scheduler/status").status_code == 401

    def test_auth_login_requires_token(self, client):
        # follow_redirects=False: a successful (authorized) call 302s to
        # Google, which isn't what this test is checking.
        res = client.get("/auth/google/login", follow_redirects=False)
        assert res.status_code == 401


class TestPublicRoutes:
    def test_health_is_public(self, client):
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

    def test_debug_anthropic_check_route_is_gone(self, client, auth_headers):
        res = client.get("/debug/anthropic-check", headers=auth_headers)
        assert res.status_code == 404
