from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .errors import (
    APIConnectionError,
    APIConnectionTimeoutError,
    APIResponseValidationError,
    create_api_error,
)

ModelT = TypeVar("ModelT", bound=BaseModel)
_RETRYABLE_STATUS_CODES = {408, 409, 429}
_RETRYABLE_METHODS = {"GET", "PUT", "DELETE", "HEAD", "OPTIONS"}


@dataclass(frozen=True, slots=True)
class RequestOptions:
    """Per-request transport overrides."""

    timeout: float | None = None
    max_retries: int | None = None
    headers: dict[str, str] | None = None
    retry_non_idempotent: bool = False

    def __post_init__(self) -> None:
        if self.timeout is not None and self.timeout < 0:
            raise ValueError("timeout must be non-negative")
        if self.max_retries is not None and self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")


def _retry_delay(attempt: int, response: httpx.Response | None = None) -> float:
    if response is not None:
        retry_after = response.headers.get("retry-after")
        if retry_after:
            try:
                return max(0.0, min(float(retry_after), 60.0))
            except ValueError:
                try:
                    parsed = parsedate_to_datetime(retry_after)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    seconds = (parsed - datetime.now(timezone.utc)).total_seconds()
                    return max(0.0, min(seconds, 60.0))
                except (TypeError, ValueError, OverflowError):
                    pass
    return float(min(0.25 * (2**attempt) + random.uniform(0, 0.1), 2.0))


def _is_retryable_response(response: httpx.Response) -> bool:
    return response.status_code in _RETRYABLE_STATUS_CODES or response.status_code >= 500


def _serialize(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    return value


def _parse_response(response: httpx.Response, model: type[ModelT] | None) -> ModelT | None:
    if response.is_error:
        raise create_api_error(response)
    if model is None:
        return None
    try:
        return model.model_validate(response.json())
    except (ValueError, ValidationError) as error:
        raise APIResponseValidationError(
            f"Response did not match {model.__name__}: {error}", response=response
        ) from error


class SyncTransport:
    def __init__(
        self,
        *,
        base_url: str,
        headers: dict[str, str],
        timeout: float,
        max_retries: int,
        client: httpx.Client | None,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self._owns_client = client is None
        self.client = client or httpx.Client(base_url=base_url, headers=headers, timeout=timeout)
        self._headers = headers
        self._base_url = base_url

    def request(
        self,
        method: str,
        path: str,
        *,
        response_model: type[ModelT] | None,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        options: RequestOptions | None = None,
    ) -> ModelT | None:
        options = options or RequestOptions()
        method = method.upper()
        retries = self.max_retries if options.max_retries is None else options.max_retries
        if method not in _RETRYABLE_METHODS and not options.retry_non_idempotent:
            retries = 0
        headers = {**self._headers, **(options.headers or {})}
        timeout = self.timeout if options.timeout is None else options.timeout

        for attempt in range(retries + 1):
            try:
                response = self.client.request(
                    method,
                    f"{self._base_url}{path}",
                    params=_serialize(query),
                    json=_serialize(body) if body is not None else None,
                    headers=headers,
                    timeout=timeout,
                )
            except httpx.TimeoutException as error:
                if attempt >= retries:
                    raise APIConnectionTimeoutError("Request timed out.") from error
                time.sleep(_retry_delay(attempt))
                continue
            except httpx.RequestError as error:
                if attempt >= retries:
                    raise APIConnectionError("Connection failed.") from error
                time.sleep(_retry_delay(attempt))
                continue

            if attempt < retries and _is_retryable_response(response):
                delay = _retry_delay(attempt, response)
                response.close()
                time.sleep(delay)
                continue
            return _parse_response(response, response_model)
        raise APIConnectionError("Connection failed.")  # pragma: no cover

    def close(self) -> None:
        if self._owns_client:
            self.client.close()


class AsyncTransport:
    def __init__(
        self,
        *,
        base_url: str,
        headers: dict[str, str],
        timeout: float,
        max_retries: int,
        client: httpx.AsyncClient | None,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            base_url=base_url, headers=headers, timeout=timeout
        )
        self._headers = headers
        self._base_url = base_url

    async def request(
        self,
        method: str,
        path: str,
        *,
        response_model: type[ModelT] | None,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        options: RequestOptions | None = None,
    ) -> ModelT | None:
        options = options or RequestOptions()
        method = method.upper()
        retries = self.max_retries if options.max_retries is None else options.max_retries
        if method not in _RETRYABLE_METHODS and not options.retry_non_idempotent:
            retries = 0
        headers = {**self._headers, **(options.headers or {})}
        timeout = self.timeout if options.timeout is None else options.timeout

        for attempt in range(retries + 1):
            try:
                response = await self.client.request(
                    method,
                    f"{self._base_url}{path}",
                    params=_serialize(query),
                    json=_serialize(body) if body is not None else None,
                    headers=headers,
                    timeout=timeout,
                )
            except httpx.TimeoutException as error:
                if attempt >= retries:
                    raise APIConnectionTimeoutError("Request timed out.") from error
                await asyncio.sleep(_retry_delay(attempt))
                continue
            except httpx.RequestError as error:
                if attempt >= retries:
                    raise APIConnectionError("Connection failed.") from error
                await asyncio.sleep(_retry_delay(attempt))
                continue

            if attempt < retries and _is_retryable_response(response):
                delay = _retry_delay(attempt, response)
                await response.aclose()
                await asyncio.sleep(delay)
                continue
            return _parse_response(response, response_model)
        raise APIConnectionError("Connection failed.")  # pragma: no cover

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()
