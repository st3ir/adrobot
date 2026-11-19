"""Transport-level hardening: headers, body limits, rate limiting, errors."""

from __future__ import annotations

import httpx
import pytest
from app.core.config import Settings
from app.core.container import build_container
from app.main import create_app
from pydantic import SecretStr, ValidationError

from tests.fakes import FakeKeitaro


class TestSecurityHeaders:
    async def test_every_response_is_hardened(self, client: httpx.AsyncClient) -> None:
        headers = (await client.get("/health")).headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in headers["content-security-policy"]
        assert "default-src 'self'" in headers["content-security-policy"]

    async def test_api_responses_are_not_cached(
        self, auth_client: httpx.AsyncClient
    ) -> None:
        response = await auth_client.get("/api/v1/offers")
        assert response.headers["cache-control"] == "no-store"

    async def test_unauthorised_responses_are_hardened_too(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.get("/api/v1/offers")
        assert response.status_code == 401
        assert response.headers["x-frame-options"] == "DENY"


class TestBodyLimit:
    async def test_oversized_bodies_are_refused(
        self, auth_client: httpx.AsyncClient
    ) -> None:
        response = await auth_client.post(
            "/api/v1/campaigns",
            json={"name": "x" * 200_000, "geo": "AU", "offer_id": 4100},
        )
        assert response.status_code == 413


class TestRateLimit:
    async def test_the_api_is_rate_limited(self, settings: Settings) -> None:
        limited = settings.model_copy(
            update={"api_rate_limit_requests": 3, "api_rate_limit_window_seconds": 60}
        )
        container = build_container(limited, keitaro=FakeKeitaro())
        try:
            app = create_app(limited, container_factory=lambda _: container)
            app.state.container = container
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                statuses = [(await http.get("/api/v1/offers")).status_code for _ in range(5)]
        finally:
            await container.aclose()
        assert statuses[-1] == 429

    async def test_health_is_not_rate_limited(self, client: httpx.AsyncClient) -> None:
        statuses = [(await client.get("/health")).status_code for _ in range(50)]
        assert set(statuses) == {200}


class TestErrorEnvelope:
    async def test_errors_use_a_uniform_shape(self, client: httpx.AsyncClient) -> None:
        body = (await client.get("/api/v1/offers")).json()
        assert set(body) == {"code", "message"}

    async def test_unknown_routes_do_not_leak_internals(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.get("/api/v1/does-not-exist")
        assert response.status_code == 404
        assert "Traceback" not in response.text


class TestSettingsHardening:
    def test_production_requires_a_strong_session_secret(self) -> None:
        with pytest.raises(ValidationError):
            Settings(
                environment="production",
                keitaro_api_key=SecretStr("k"),
                session_secret=SecretStr("too-short"),
            )

    def test_production_requires_an_api_key(self) -> None:
        with pytest.raises(ValidationError):
            Settings(environment="production", session_secret=SecretStr("a" * 48))

    def test_production_forbids_debug(self) -> None:
        with pytest.raises(ValidationError):
            Settings(
                environment="production",
                debug=True,
                keitaro_api_key=SecretStr("k"),
                session_secret=SecretStr("a" * 48),
            )

    def test_production_forbids_insecure_cookies(self) -> None:
        with pytest.raises(ValidationError):
            Settings(
                environment="production",
                keitaro_api_key=SecretStr("k"),
                session_secret=SecretStr("a" * 48),
                cookie_secure=False,
            )

    def test_secrets_are_not_printed(self) -> None:
        settings = Settings(keitaro_api_key=SecretStr("super-secret-key"))
        assert "super-secret-key" not in repr(settings)
        assert "super-secret-key" not in str(settings.keitaro_api_key)

    @pytest.mark.parametrize("prefix", ["", "Test_", "test ivanov", "a" * 50])
    def test_campaign_prefix_is_validated(self, prefix: str) -> None:
        if prefix == "Test_":  # upper case is normalised, not rejected
            assert Settings(campaign_name_prefix=prefix).campaign_name_prefix == "test_"
            return
        with pytest.raises(ValidationError):
            Settings(campaign_name_prefix=prefix)

    def test_api_root_is_derived_from_the_base_url(self) -> None:
        settings = Settings(keitaro_base_url="https://tlgk.host/")
        assert settings.keitaro_api_root == "https://tlgk.host/admin_api/v1"
