"""HTTP transport: error mapping, retries and path safety."""

from __future__ import annotations

import httpx
import pytest
import respx
from app.core.exceptions import (
    KeitaroAuthError,
    KeitaroError,
    KeitaroNotFoundError,
    KeitaroUnavailableError,
    KeitaroValidationError,
)
from app.keitaro.client import KeitaroClient

API_ROOT = "https://keitaro.test/admin_api/v1"


def make_client(**kwargs: object) -> KeitaroClient:
    return KeitaroClient(api_root=API_ROOT, api_key="secret-key", **kwargs)  # type: ignore[arg-type]


class TestAuthentication:
    @respx.mock
    async def test_sends_the_api_key_header(self) -> None:
        route = respx.get(f"{API_ROOT}/offers").mock(httpx.Response(200, json=[]))
        async with make_client() as client:
            await client.get("/offers")
        assert route.calls.last.request.headers["Api-Key"] == "secret-key"

    @respx.mock
    async def test_does_not_follow_redirects(self) -> None:
        """A redirect must never leak the Api-Key header to another host."""
        respx.get(f"{API_ROOT}/offers").mock(
            httpx.Response(302, headers={"Location": "https://evil.test/steal"})
        )
        async with make_client() as client:
            with pytest.raises(KeitaroError):
                await client.get("/offers")


class TestErrorMapping:
    @respx.mock
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (401, KeitaroAuthError),
            (403, KeitaroAuthError),
            (404, KeitaroNotFoundError),
            (400, KeitaroValidationError),
            (422, KeitaroValidationError),
        ],
    )
    async def test_maps_status_codes(self, status: int, expected: type[Exception]) -> None:
        respx.get(f"{API_ROOT}/offers").mock(httpx.Response(status, json={"error": "nope"}))
        async with make_client(max_retries=0) as client:
            with pytest.raises(expected):
                await client.get("/offers")

    @respx.mock
    async def test_server_errors_become_unavailable(self) -> None:
        respx.get(f"{API_ROOT}/offers").mock(httpx.Response(500, text="boom"))
        async with make_client(max_retries=0) as client:
            with pytest.raises(KeitaroUnavailableError):
                await client.get("/offers")

    @respx.mock
    async def test_surfaces_a_short_upstream_message(self) -> None:
        respx.post(f"{API_ROOT}/campaigns").mock(
            httpx.Response(400, json={"error": "name is required"})
        )
        async with make_client() as client:
            with pytest.raises(KeitaroValidationError) as info:
                await client.post("/campaigns", json={})
        assert "name is required" in info.value.safe_message

    @respx.mock
    async def test_surfaces_per_field_errors(self) -> None:
        """Keitaro answers with {"field": ["message"]} and no envelope."""
        respx.post(f"{API_ROOT}/campaigns").mock(
            httpx.Response(422, json={"name": ["Name has already been used"]})
        )
        async with make_client() as client:
            with pytest.raises(KeitaroValidationError) as info:
                await client.post("/campaigns", json={})
        assert "name: Name has already been used" in info.value.safe_message

    @respx.mock
    async def test_timeouts_become_unavailable(self) -> None:
        respx.get(f"{API_ROOT}/offers").mock(side_effect=httpx.ConnectTimeout("slow"))
        async with make_client(max_retries=0) as client:
            with pytest.raises(KeitaroUnavailableError):
                await client.get("/offers")

    @respx.mock
    async def test_malformed_json_is_reported(self) -> None:
        respx.get(f"{API_ROOT}/offers").mock(
            httpx.Response(200, text="<html>", headers={"Content-Type": "application/json"})
        )
        async with make_client() as client:
            with pytest.raises(KeitaroError):
                await client.get("/offers")


class TestRetries:
    @respx.mock
    async def test_retries_idempotent_requests(self) -> None:
        route = respx.get(f"{API_ROOT}/offers").mock(
            side_effect=[httpx.Response(503), httpx.Response(200, json=[{"id": 1, "name": "o"}])]
        )
        async with make_client(max_retries=2) as client:
            assert await client.get("/offers") == [{"id": 1, "name": "o"}]
        assert route.call_count == 2

    @respx.mock
    async def test_does_not_retry_post(self) -> None:
        """Re-sending a POST could create a second campaign."""
        route = respx.post(f"{API_ROOT}/campaigns").mock(httpx.Response(503))
        async with make_client(max_retries=3) as client:
            with pytest.raises(KeitaroUnavailableError):
                await client.post("/campaigns", json={})
        assert route.call_count == 1


class TestPathSafety:
    @pytest.mark.parametrize(
        "path",
        [
            "//evil.test/steal",
            "https://evil.test/steal",
            "/campaigns/../../admin",
            "/campaigns/1?x=1",
            "campaigns",
        ],
    )
    async def test_rejects_paths_that_could_leave_the_api_root(self, path: str) -> None:
        async with make_client() as client:
            with pytest.raises(ValueError, match="Unsafe"):
                await client.get(path)

    @respx.mock
    async def test_drops_none_query_parameters(self) -> None:
        route = respx.get(f"{API_ROOT}/offers").mock(httpx.Response(200, json=[]))
        async with make_client() as client:
            await client.get("/offers", params={"q": "x", "limit": None})
        assert route.calls.last.request.url.params.get("limit") is None
        assert route.calls.last.request.url.params["q"] == "x"
