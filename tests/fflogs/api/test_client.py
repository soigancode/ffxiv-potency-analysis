"""Authenticated FF Logs quota lookup."""

import httpx
import pytest

from ffxiv_potency.fflogs.client import FFLogsClient, FFLogsError


def test_rate_limit_uses_the_authenticated_client_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "test-token"})
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.url.path == "/api/v2/client"
        assert request.content and b"rateLimitData" in request.content
        return httpx.Response(200, json={"data": {"rateLimitData": {
            "limitPerHour": 3600, "pointsSpentThisHour": 125.25, "pointsResetIn": 83,
        }}})

    with FFLogsClient("id", "secret", transport=httpx.MockTransport(handler)) as client:
        usage = client.rate_limit()

    assert usage.limit_per_hour == 3600
    assert usage.points_spent == 125.25
    assert usage.resets_in_seconds == 83


def test_rate_limit_rejects_missing_or_invalid_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "test-token"})
        return httpx.Response(200, json={"data": {"rateLimitData": {
            "limitPerHour": 3600, "pointsSpentThisHour": None, "pointsResetIn": 83,
        }}})

    with (FFLogsClient("id", "secret", transport=httpx.MockTransport(handler)) as client,
          pytest.raises(FFLogsError, match="invalid rate limit data")):
        client.rate_limit()


@pytest.mark.parametrize("status,body,retry,expected", [
    (429, {}, "93", "retry after 93 seconds"),
    (200, {"errors": [{"message": "Rate limit exceeded"}]}, None,
     "ffxiv-potency fflogs limit"),
    (403, {"errors": [{"message": "Request rejected",
                       "extensions": {"code": "RATE_LIMITED"}}]}, None,
     "FF Logs API rate limit reached"),
])
def test_graphql_rate_limit_errors_are_actionable(
    status: int, body: dict, retry: str | None, expected: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "test-token"})
        return httpx.Response(
            status, json=body, headers={"Retry-After": retry} if retry else {},
        )

    with (FFLogsClient("id", "secret", transport=httpx.MockTransport(handler)) as client,
          pytest.raises(FFLogsError) as raised):
        client.graphql("query { reportData { __typename } }", {})
    assert expected in str(raised.value)


def test_unrelated_graphql_error_is_not_labelled_rate_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "test-token"})
        return httpx.Response(200, json={"errors": [{"message": "Unknown report"}]})

    with (FFLogsClient("id", "secret", transport=httpx.MockTransport(handler)) as client,
          pytest.raises(FFLogsError, match="Unknown report") as raised):
        client.graphql("query { reportData { __typename } }", {})
    assert "rate limit" not in str(raised.value).lower()


def test_oauth_rate_limit_is_reported_without_exposing_credentials() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/oauth/token"
        return httpx.Response(429, headers={"Retry-After": "60"})

    with pytest.raises(FFLogsError, match="retry after 60 seconds") as raised:
        FFLogsClient("private-id", "private-secret", transport=httpx.MockTransport(handler))
    assert "private-secret" not in str(raised.value)
