from __future__ import annotations

import os
from typing import Any

import httpx

from ._transport import AsyncTransport, SyncTransport
from ._version import __version__
from .errors import PostPeerError
from .resources._generated import AsyncPostPeerResources, SyncPostPeerResources

DEFAULT_BASE_URL = "https://api.postpeer.dev"
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 2


def _validate_options(timeout: float, max_retries: int) -> None:
    if timeout < 0:
        raise PostPeerError("timeout must be non-negative.")
    if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 0:
        raise PostPeerError("max_retries must be a non-negative integer.")


def _resolve_headers(api_key: str, default_headers: dict[str, str] | None) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "User-Agent": f"postpeer-python/{__version__}",
        **(default_headers or {}),
        "x-access-key": api_key,
    }


class PostPeer(SyncPostPeerResources):
    """Synchronous client for the PostPeer API."""

    DEFAULT_TIMEOUT = DEFAULT_TIMEOUT
    DEFAULT_MAX_RETRIES = DEFAULT_MAX_RETRIES

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        default_headers: dict[str, str] | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        resolved_key = api_key or os.environ.get("POSTPEER_API_KEY")
        if not resolved_key:
            raise PostPeerError(
                "The POSTPEER_API_KEY environment variable is missing or empty. "
                "Set it or pass PostPeer(api_key='your-key')."
            )
        _validate_options(timeout, max_retries)
        self.api_key = resolved_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        transport = SyncTransport(
            base_url=self.base_url,
            headers=_resolve_headers(resolved_key, default_headers),
            timeout=timeout,
            max_retries=max_retries,
            client=http_client,
        )
        super().__init__(transport)

    @property
    def raw_client(self) -> httpx.Client:
        return self._transport.client

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> PostPeer:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


class AsyncPostPeer(AsyncPostPeerResources):
    """Asynchronous client for the PostPeer API."""

    DEFAULT_TIMEOUT = DEFAULT_TIMEOUT
    DEFAULT_MAX_RETRIES = DEFAULT_MAX_RETRIES

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        default_headers: dict[str, str] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        resolved_key = api_key or os.environ.get("POSTPEER_API_KEY")
        if not resolved_key:
            raise PostPeerError(
                "The POSTPEER_API_KEY environment variable is missing or empty. "
                "Set it or pass AsyncPostPeer(api_key='your-key')."
            )
        _validate_options(timeout, max_retries)
        self.api_key = resolved_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        transport = AsyncTransport(
            base_url=self.base_url,
            headers=_resolve_headers(resolved_key, default_headers),
            timeout=timeout,
            max_retries=max_retries,
            client=http_client,
        )
        super().__init__(transport)

    @property
    def raw_client(self) -> httpx.AsyncClient:
        return self._transport.client

    async def aclose(self) -> None:
        await self._transport.close()

    async def __aenter__(self) -> AsyncPostPeer:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()
