from __future__ import annotations

from typing import Any

import httpx


class PostPeerError(Exception):
    """Base exception for the PostPeer SDK."""


class APIError(PostPeerError):
    """An error response returned by the PostPeer API."""

    def __init__(
        self,
        status: int,
        message: str,
        *,
        code: str | None = None,
        details: Any = None,
        headers: httpx.Headers | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.details = details
        self.headers = headers or httpx.Headers()
        self.request_id = request_id


class BadRequestError(APIError):
    pass


class AuthenticationError(APIError):
    pass


class PermissionDeniedError(APIError):
    pass


class NotFoundError(APIError):
    pass


class ConflictError(APIError):
    pass


class UnprocessableEntityError(APIError):
    pass


class RateLimitError(APIError):
    pass


class InternalServerError(APIError):
    pass


class APIConnectionError(PostPeerError):
    """The SDK could not connect to the API."""


class APIConnectionTimeoutError(APIConnectionError):
    """A request exceeded its configured timeout."""


class APIUserAbortError(APIConnectionError):
    """A request was cancelled by its caller."""


class APIResponseValidationError(PostPeerError):
    """A successful API response did not match the OpenAPI contract."""

    def __init__(self, message: str, *, response: httpx.Response) -> None:
        super().__init__(message)
        self.response = response


_STATUS_ERRORS: dict[int, type[APIError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    422: UnprocessableEntityError,
    429: RateLimitError,
}


def create_api_error(response: httpx.Response) -> APIError:
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text

    message = response.reason_phrase or f"Request failed with status {response.status_code}."
    code: str | None = None
    if isinstance(body, dict):
        raw_message = body.get("message", body.get("error"))
        if isinstance(raw_message, str) and raw_message:
            message = raw_message
        raw_code = body.get("code")
        if isinstance(raw_code, str):
            code = raw_code
    elif isinstance(body, str) and body:
        message = body

    error_type = _STATUS_ERRORS.get(response.status_code)
    if error_type is None:
        error_type = InternalServerError if response.status_code >= 500 else APIError
    return error_type(
        response.status_code,
        message,
        code=code,
        details=body,
        headers=response.headers,
        request_id=response.headers.get("x-request-id"),
    )
