"""Small authenticated client for the FF Logs v2 GraphQL API."""

import os
from typing import Any, Self

import httpx

TOKEN_URL = "https://www.fflogs.com/oauth/token"
GRAPHQL_URL = "https://www.fflogs.com/api/v2/client"


class FFLogsError(RuntimeError):
    """Authentication, GraphQL, or response-shape failure."""


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
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise FFLogsError("GraphQL response was not an object")
        if payload.get("errors"):
            raise FFLogsError(f"GraphQL returned errors: {payload['errors']}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise FFLogsError("GraphQL response did not contain data")
        return data

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
