"""Authentication, session and CSRF behaviour of the HTTP API."""

from __future__ import annotations

import httpx
import pytest
from app.core.container import Container
from app.db.models import AuditAction, AuditLogEntry, User
from sqlalchemy import select

from tests.conftest import TEST_EMAIL, TEST_PASSWORD


class TestLogin:
    async def test_successful_login_sets_an_http_only_cookie(
        self, client: httpx.AsyncClient, user: User, container: Container
    ) -> None:
        response = await client.post(
            "/api/v1/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
        )
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert container.settings.session_cookie_name in cookie
        assert "HttpOnly" in cookie
        assert "SameSite=strict" in cookie.replace("samesite", "SameSite")

    async def test_returns_a_csrf_token_and_the_name_prefix(
        self, client: httpx.AsyncClient, user: User
    ) -> None:
        response = await client.post(
            "/api/v1/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
        )
        body = response.json()
        assert len(body["csrf_token"]) >= 32
        assert body["campaign_name_prefix"] == "test_ivanov_"

    async def test_email_is_case_insensitive(
        self, client: httpx.AsyncClient, user: User
    ) -> None:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": TEST_EMAIL.upper(), "password": TEST_PASSWORD},
        )
        assert response.status_code == 200

    @pytest.mark.parametrize(
        ("email", "password"),
        [
            (TEST_EMAIL, "wrong-password-value"),
            ("nobody@example.com", TEST_PASSWORD),
        ],
    )
    async def test_rejects_bad_credentials_with_the_same_message(
        self, client: httpx.AsyncClient, user: User, email: str, password: str
    ) -> None:
        response = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        )
        assert response.status_code == 401
        assert response.json()["message"] == "Invalid email or password."

    async def test_never_echoes_the_password(
        self, client: httpx.AsyncClient, user: User
    ) -> None:
        response = await client.post(
            "/api/v1/auth/login", json={"email": TEST_EMAIL, "password": "wrong-password"}
        )
        assert "wrong-password" not in response.text

    async def test_inactive_account_cannot_log_in(
        self, client: httpx.AsyncClient, user: User, container: Container
    ) -> None:
        async with container.session_factory() as session, session.begin():
            account = await session.get(User, user.id)
            assert account is not None
            account.is_active = False
        response = await client.post(
            "/api/v1/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
        )
        assert response.status_code == 401

    async def test_brute_force_is_rate_limited(
        self, client: httpx.AsyncClient, user: User
    ) -> None:
        payload = {"email": TEST_EMAIL, "password": "definitely-wrong"}
        statuses = [
            (await client.post("/api/v1/auth/login", json=payload)).status_code
            for _ in range(7)
        ]
        assert statuses[-1] == 429

    async def test_failed_logins_are_audited(
        self, client: httpx.AsyncClient, user: User, container: Container
    ) -> None:
        await client.post(
            "/api/v1/auth/login", json={"email": TEST_EMAIL, "password": "definitely-wrong"}
        )
        async with container.session_factory() as session:
            actions = (await session.scalars(select(AuditLogEntry.action))).all()
        assert AuditAction.LOGIN_FAILED in actions

    async def test_short_passwords_are_rejected_before_hashing(
        self, client: httpx.AsyncClient, user: User
    ) -> None:
        response = await client.post(
            "/api/v1/auth/login", json={"email": TEST_EMAIL, "password": "short"}
        )
        assert response.status_code == 422


class TestSession:
    async def test_anonymous_requests_are_rejected(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/api/v1/auth/session")).status_code == 401

    async def test_authenticated_session_is_returned(
        self, auth_client: httpx.AsyncClient
    ) -> None:
        response = await auth_client.get("/api/v1/auth/session")
        assert response.status_code == 200
        assert response.json()["email"] == TEST_EMAIL

    async def test_a_forged_cookie_is_rejected(self, client: httpx.AsyncClient) -> None:
        client.cookies.set("adrobot_session", "forged.value.here")
        assert (await client.get("/api/v1/auth/session")).status_code == 401

    async def test_logout_clears_the_session(self, auth_client: httpx.AsyncClient) -> None:
        assert (await auth_client.post("/api/v1/auth/logout")).status_code == 200
        auth_client.cookies.clear()
        assert (await auth_client.get("/api/v1/auth/session")).status_code == 401


class TestCsrf:
    async def test_state_changing_request_without_the_header_is_refused(
        self, auth_client: httpx.AsyncClient
    ) -> None:
        del auth_client.headers["X-CSRF-Token"]
        response = await auth_client.post(
            "/api/v1/campaigns", json={"name": "c", "geo": "AU", "offer_id": 4100}
        )
        assert response.status_code == 403
        assert response.json()["code"] == "csrf_failed"

    async def test_a_wrong_token_is_refused(self, auth_client: httpx.AsyncClient) -> None:
        auth_client.headers["X-CSRF-Token"] = "not-the-right-token"
        response = await auth_client.post(
            "/api/v1/campaigns", json={"name": "c", "geo": "AU", "offer_id": 4100}
        )
        assert response.status_code == 403

    async def test_read_requests_do_not_need_a_token(
        self, auth_client: httpx.AsyncClient
    ) -> None:
        del auth_client.headers["X-CSRF-Token"]
        assert (await auth_client.get("/api/v1/offers")).status_code == 200
