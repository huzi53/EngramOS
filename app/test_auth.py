"""Assert-based self-check for auth.py — DB-free (monkeypatches the user lookup
with a known bcrypt hash). Run: python test_auth.py  OR  python -m pytest test_auth.py
This is the CI gate.
"""
import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ACCESS_TTL_MIN", "30")
os.environ.setdefault("REFRESH_TTL_DAYS", "60")
os.environ.setdefault("DATABASE_URL", "postgresql://unused/unused")  # never connected in tests

import bcrypt
from fastapi import FastAPI
from fastapi.testclient import TestClient

import auth

TEST_PASSWORD = "correct horse battery staple"
TEST_USER = {
    "id": "11111111-1111-1111-1111-111111111111",
    "username": "testuser",
    "password_hash": bcrypt.hashpw(TEST_PASSWORD.encode(), bcrypt.gensalt()).decode(),
}


def _fake_get_user_by_username(username):
    return TEST_USER if username == TEST_USER["username"] else None


auth.get_user_by_username = _fake_get_user_by_username  # DB-free stub

app = FastAPI()
app.include_router(auth.router)
client = TestClient(app)


def _login():
    r = client.post("/api/v1/auth/login", json={"username": "testuser", "password": TEST_PASSWORD})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "access_token" in body and "refresh_token" in body
    return body


def test_login_success_returns_tokens():
    _login()


def test_login_wrong_password_401():
    r = client.post("/api/v1/auth/login", json={"username": "testuser", "password": "nope"})
    assert r.status_code == 401


def test_me_without_token_401():
    r = client.get("/api/v1/me")
    assert r.status_code == 401


def test_me_with_access_token_200():
    tokens = _login()
    r = client.get("/api/v1/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert r.status_code == 200, r.text
    assert r.json()["username"] == "testuser"


def test_me_with_refresh_token_rejected():
    tokens = _login()
    r = client.get("/api/v1/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"})
    assert r.status_code == 401


def test_refresh_mints_new_access_token():
    tokens = _login()
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200, r.text
    assert "access_token" in r.json()


if __name__ == "__main__":
    test_login_success_returns_tokens()
    test_login_wrong_password_401()
    test_me_without_token_401()
    test_me_with_access_token_200()
    test_me_with_refresh_token_rejected()
    test_refresh_mints_new_access_token()
    print("all asserts passed")
