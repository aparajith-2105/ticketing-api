import pytest


def register(client, email="ann@test.com", role="attendee", password="Passw0rd123"):
    return client.post("/auth/register", json={
        "email": email, "password": password, "full_name": "Ann", "role": role})


def login(client, email="ann@test.com", password="Passw0rd123"):
    return client.post("/auth/login", json={"email": email, "password": password})


def test_register_success_never_exposes_password(client):
    r = register(client)
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "ann@test.com" and body["role"] == "attendee"
    assert "password" not in body and "password_hash" not in body


def test_register_duplicate_email_is_rejected_case_insensitively(client):
    assert register(client).status_code == 201
    r = register(client, email="ANN@test.com")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "EMAIL_TAKEN"


@pytest.mark.parametrize("override", [
    {"email": "not-an-email"},
    {"password": "Ab1"},                # too short
    {"password": "onlylettersnodigit"}, # no digit
    {"role": "admin"},                  # role not allowed
    {"full_name": ""},
])
def test_register_rejects_invalid_payloads(client, override):
    payload = {"email": "ann@test.com", "password": "Passw0rd123",
               "full_name": "Ann", "role": "attendee", **override}
    r = client.post("/auth/register", json=payload)
    assert r.status_code == 422
    error = r.json()["error"]
    assert error["code"] == "VALIDATION_ERROR" and error["details"]


def test_register_rejects_empty_body(client):
    r = client.post("/auth/register", json={})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_login_returns_token_pair(client):
    register(client)
    r = login(client)
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]


def test_login_fails_with_same_error_for_wrong_password_and_unknown_email(client):
    register(client)
    for r in (login(client, password="WrongPass123"), login(client, email="nobody@test.com")):
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_me_requires_a_valid_access_token(client):
    register(client)
    tokens = login(client).json()

    assert client.get("/auth/me").json()["error"]["code"] == "NOT_AUTHENTICATED"
    bad = client.get("/auth/me", headers={"Authorization": "Bearer garbage"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "INVALID_TOKEN"

    ok = client.get("/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert ok.status_code == 200 and ok.json()["email"] == "ann@test.com"


def test_refresh_token_cannot_be_used_as_access_token(client):
    register(client)
    tokens = login(client).json()
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"})
    assert r.status_code == 401


def test_refresh_rotation_and_reuse_detection(client):
    register(client)
    first = login(client).json()

    rotated = client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert rotated.status_code == 200
    second = rotated.json()
    assert second["refresh_token"] != first["refresh_token"]

    # Replaying the OLD token = suspected theft -> rejected, and the whole family is revoked.
    replay = client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "TOKEN_REUSED"

    # So even the legitimately rotated token is now dead.
    after = client.post("/auth/refresh", json={"refresh_token": second["refresh_token"]})
    assert after.status_code == 401


def test_logout_revokes_the_session(client):
    register(client)
    tokens = login(client).json()
    assert client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]}).status_code == 204
    r = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401
