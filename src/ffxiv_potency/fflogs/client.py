"""Small authenticated client for the FF Logs v2 GraphQL API."""

import os
from dataclasses import dataclass
from typing import Any, Self

import httpx

TOKEN_URL = "https://www.fflogs.com/oauth/token"
GRAPHQL_URL = "https://www.fflogs.com/api/v2/client"
_RATE_LIMIT_QUERY = """
query RateLimit {
  rateLimitData { limitPerHour pointsSpentThisHour pointsResetIn }
}
"""


class FFLogsError(RuntimeError):
    """Authentication, GraphQL, or response-shape failure."""


def _rate_limit_message(retry_after: str | None = None) -> str:
    message = "FF Logs API rate limit reached"
    if retry_after is not None and retry_after.isdecimal():
        message += f"; retry after {retry_after} seconds"
    return message + ". Check usage and reset time with 'ffxiv-potency fflogs limit'."


def _rate_limit_errors(errors: Any) -> bool:
    if not isinstance(errors, list):
        return False
    for error in errors:
        if not isinstance(error, dict):
            continue
        message = error.get("message")
        extensions = error.get("extensions")
        code = extensions.get("code") if isinstance(extensions, dict) else None
        if isinstance(message, str) and any(
            text in message.casefold()
            for text in ("rate limit", "rate_limit", "too many requests", "points per hour")
        ):
            return True
        if isinstance(code, str) and code.casefold() in {
            "rate_limited", "rate_limit_exceeded", "too_many_requests",
        }:
            return True
    return False


@dataclass(frozen=True, slots=True)
class RateLimitUsage:
    limit_per_hour: int
    points_spent: float
    resets_in_seconds: int


class FFLogsClient:
    @classmethod
    def from_environment(
        cls,
        client_id: str | None = None,
        client_secret: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> Self:
        """Use explicit credentials or fall back to FF Logs environment settings."""
        return cls(
            client_id or os.environ.get("FFLOGS_CLIENT_ID", ""),
            client_secret or os.environ.get("FFLOGS_CLIENT_SECRET", ""),
            transport=transport,
        )

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not client_id or not client_secret:
            raise FFLogsError("FFLOGS_CLIENT_ID and FFLOGS_CLIENT_SECRET are required")
        self._http = httpx.Client(timeout=30.0, transport=transport)
        self._token = self._authenticate(client_id, client_secret)

    def _authenticate(self, client_id: str, client_secret: str) -> str:
        response = self._http.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
        )
        if response.status_code == 429:
            raise FFLogsError(_rate_limit_message(response.headers.get("Retry-After")))
        response.raise_for_status()
        payload = response.json()
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise FFLogsError("OAuth response did not contain an access token")
        return token

    def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        response = self._http.post(
            GRAPHQL_URL,
            headers={"Authorization": f"Bearer {self._token}"},
            json={"query": query, "variables": variables},
        )
        if response.status_code == 429:
            raise FFLogsError(_rate_limit_message(response.headers.get("Retry-After")))
        if response.status_code == 403:
            try:
                denied_payload = response.json()
            except ValueError:
                denied_payload = None
            if isinstance(denied_payload, dict) and _rate_limit_errors(denied_payload.get("errors")):
                raise FFLogsError(_rate_limit_message(response.headers.get("Retry-After")))
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise FFLogsError("GraphQL response was not an object")
        if payload.get("errors"):
            if _rate_limit_errors(payload["errors"]):
                raise FFLogsError(_rate_limit_message(response.headers.get("Retry-After")))
            raise FFLogsError(f"GraphQL returned errors: {payload['errors']}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise FFLogsError("GraphQL response did not contain data")
        return data

    def rate_limit(self) -> RateLimitUsage:
        """Retrieve usage for the authenticated FF Logs API key."""
        data = self.graphql(_RATE_LIMIT_QUERY, {})
        usage = data.get("rateLimitData")
        if not isinstance(usage, dict):
            raise FFLogsError("FF Logs did not return rate limit data")
        limit = usage.get("limitPerHour")
        spent = usage.get("pointsSpentThisHour")
        reset = usage.get("pointsResetIn")
        if (
            not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0
            or not isinstance(spent, (int, float)) or isinstance(spent, bool) or spent < 0
            or not isinstance(reset, int) or isinstance(reset, bool) or reset < 0
        ):
            raise FFLogsError("FF Logs returned invalid rate limit data")
        return RateLimitUsage(limit, float(spent), reset)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
