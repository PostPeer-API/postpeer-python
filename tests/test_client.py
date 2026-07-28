from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from postpeer import (
    APIConnectionError,
    APIConnectionTimeoutError,
    APIError,
    APIResponseValidationError,
    AsyncPostPeer,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    PostPeer,
    PostPeerError,
    RateLimitError,
    RequestOptions,
    UnprocessableEntityError,
)
from postpeer.types import CreatePostResponse, HealthCheckResponse


def json_response(
    request: httpx.Request,
    body: Any,
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers, request=request)


def sync_client(handler: Callable[[httpx.Request], httpx.Response], **kwargs: Any) -> PostPeer:
    raw = httpx.Client(transport=httpx.MockTransport(handler))
    return PostPeer(api_key="test-key", http_client=raw, **kwargs)


def test_requires_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POSTPEER_API_KEY", raising=False)
    with pytest.raises(PostPeerError):
        PostPeer()


def test_reads_api_key_from_environment_and_returns_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POSTPEER_API_KEY", "env-key")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return json_response(request, {"ok": True})

    raw = httpx.Client(transport=httpx.MockTransport(handler))
    client = PostPeer(http_client=raw)
    response = client.health.check()

    assert isinstance(response, HealthCheckResponse)
    assert response.ok is True
    assert requests[0].headers["x-access-key"] == "env-key"
    assert requests[0].headers["user-agent"] == "postpeer-python/0.1.1"
    assert requests[0].url == "https://api.postpeer.dev/v1/health"
    client.close()
    assert not raw.is_closed
    raw.close()


def test_clients_are_isolated() -> None:
    headers: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        headers.append(request.headers["x-access-key"])
        return json_response(request, {"ok": True})

    first_raw = httpx.Client(transport=httpx.MockTransport(handler))
    second_raw = httpx.Client(transport=httpx.MockTransport(handler))
    first = PostPeer(api_key="first", http_client=first_raw)
    second = PostPeer(api_key="second", http_client=second_raw)

    first.health.check()
    second.health.check()

    assert headers == ["first", "second"]
    first_raw.close()
    second_raw.close()


def test_resource_structure_and_sync_async_parity() -> None:
    sync = PostPeer(api_key="test")
    asynchronous = AsyncPostPeer(api_key="test")
    pairs = [
        (sync.health.check, asynchronous.health.check),
        (sync.posts.create, asynchronous.posts.create),
        (sync.posts.scheduled.edit, asynchronous.posts.scheduled.edit),
        (sync.posts.scheduled.reschedule, asynchronous.posts.scheduled.reschedule),
        (sync.connect.linkedin.get_selection, asynchronous.connect.linkedin.get_selection),
        (sync.connect.integrations.list, asynchronous.connect.integrations.list),
        (sync.ai.generate_image, asynchronous.ai.generate_image),
    ]

    for sync_method, async_method in pairs:
        assert inspect.signature(sync_method) == inspect.signature(async_method)
        assert inspect.iscoroutinefunction(async_method)

    sync.close()


def test_pythonic_arguments_are_serialized_to_wire_names() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return json_response(
            request,
            {
                "success": True,
                "status": "published",
                "postId": "post_123",
                "platforms": [{"platform": "twitter", "success": True}],
            },
            status=202,
        )

    client = sync_client(handler)
    response = client.posts.create(
        content="Hello",
        platforms=[{"platform": "twitter", "accountId": "integration_123"}],
        media_items=None,
        publish_now=True,
    )

    assert isinstance(response, CreatePostResponse)
    assert response.post_id == "post_123"
    assert requests[0].method == "POST"
    assert requests[0].read() == (
        b'{"content":"Hello","platforms":[{"platform":"twitter",'
        b'"accountId":"integration_123"}],"publishNow":true}'
    )


def test_path_encoding_query_arrays_and_none_omission() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return json_response(
            request,
            {"success": True, "post": {"postId": "a/b"}},
        )

    client = sync_client(handler)
    with pytest.raises(APIResponseValidationError):
        client.posts.get(post_id="a/b")
    assert requests[0].url.raw_path.endswith(b"/a%2Fb")

    with pytest.raises(APIResponseValidationError):
        client.posts.list(platform=["twitter", "linkedin"], profile_id=None)
    assert requests[1].url.params.get_list("platform") == ["twitter", "linkedin"]
    assert "profileId" not in requests[1].url.params


def test_edit_scheduled_post_with_instagram_story_config() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return json_response(
            request,
            {
                "success": True,
                "message": "Scheduled post updated",
                "postId": "post/123",
                "scheduledFor": "2026-08-01T09:00:00Z",
            },
        )

    client = sync_client(handler)
    response = client.posts.scheduled.edit(
        post_id="post/123",
        content="An Instagram Story",
        platforms=[
            {
                "platform": "instagram",
                "accountId": "instagram_123",
                "platformSpecificData": {"contentType": "story"},
            }
        ],
    )

    assert response.post_id == "post/123"
    assert requests[0].method == "PUT"
    assert requests[0].url.raw_path.endswith(b"/posts/scheduled/post%2F123")
    assert json.loads(requests[0].read()) == {
        "content": "An Instagram Story",
        "platforms": [
            {
                "platform": "instagram",
                "accountId": "instagram_123",
                "platformSpecificData": {"contentType": "story"},
            }
        ],
    }


def test_typed_api_error_preserves_context() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(
            request,
            {"code": "missing_profile", "message": "Profile not found"},
            status=404,
            headers={"x-request-id": "req_123"},
        )

    client = sync_client(handler)
    with pytest.raises(NotFoundError) as captured:
        client.profiles.get(id="missing")

    error = captured.value
    assert error.status == 404
    assert error.code == "missing_profile"
    assert error.request_id == "req_123"
    assert error.message == "Profile not found"


def test_non_json_api_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="gone", request=request)

    client = sync_client(handler)
    with pytest.raises(NotFoundError, match="gone"):
        client.profiles.get(id="missing")


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (400, BadRequestError),
        (401, AuthenticationError),
        (403, PermissionDeniedError),
        (404, NotFoundError),
        (409, ConflictError),
        (418, APIError),
        (422, UnprocessableEntityError),
        (429, RateLimitError),
        (500, InternalServerError),
    ],
)
def test_all_status_errors_are_typed(
    status: int,
    error_type: type[APIError],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(request, {"message": "failure"}, status=status)

    client = sync_client(handler, max_retries=0)
    with pytest.raises(error_type):
        client.health.check()


def test_safe_requests_retry_transient_status(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    monkeypatch.setattr("postpeer._transport.time.sleep", lambda _delay: None)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return json_response(request, {"error": "temporary"}, status=503)
        return json_response(request, {"ok": True})

    client = sync_client(handler, max_retries=2)
    assert client.health.check().ok is True
    assert calls == 3


def test_retry_after_controls_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    delays: list[float] = []
    monkeypatch.setattr("postpeer._transport.time.sleep", delays.append)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return json_response(
                request,
                {"error": "slow down"},
                status=429,
                headers={"retry-after": "1.5"},
            )
        return json_response(request, {"ok": True})

    client = sync_client(handler, max_retries=1)
    assert client.health.check().ok is True
    assert delays == [1.5]


def test_non_idempotent_requests_do_not_retry_without_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    monkeypatch.setattr("postpeer._transport.time.sleep", lambda _delay: None)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return json_response(request, {"error": "temporary"}, status=503)
        return json_response(
            request,
            {
                "success": True,
                "status": "published",
                "postId": "post_123",
                "platforms": [{"platform": "twitter", "success": True}],
            },
            status=202,
        )

    client = sync_client(handler, max_retries=2)
    with pytest.raises(InternalServerError):
        client.posts.create(
            content="Hello",
            platforms=[{"platform": "twitter", "accountId": "integration_123"}],
            publish_now=True,
        )
    assert calls == 1

    response = client.posts.create(
        content="Hello",
        platforms=[{"platform": "twitter", "accountId": "integration_123"}],
        publish_now=True,
        _request_options=RequestOptions(retry_non_idempotent=True),
    )
    assert response.post_id == "post_123"
    assert calls == 3


def test_timeout_is_typed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client = sync_client(handler, max_retries=0)
    with pytest.raises(APIConnectionTimeoutError):
        client.health.check()


def test_connection_failure_is_typed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable", request=request)

    client = sync_client(handler, max_retries=0)
    with pytest.raises(APIConnectionError):
        client.health.check()


def test_invalid_success_response_is_typed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(request, {"unexpected": True})

    client = sync_client(handler)
    with pytest.raises(APIResponseValidationError):
        client.health.check()


def test_request_options_validation() -> None:
    with pytest.raises(ValueError):
        RequestOptions(timeout=-1)
    with pytest.raises(ValueError):
        RequestOptions(max_retries=-1)


@pytest.mark.asyncio
async def test_async_client_uses_same_surface() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return json_response(request, {"ok": True})

    raw = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with AsyncPostPeer(api_key="async-key", http_client=raw) as client:
        response = await client.health.check()

    assert response.ok is True
    assert requests[0].headers["x-access-key"] == "async-key"
    assert not raw.is_closed
    await raw.aclose()


def test_generated_models_validate_constraints() -> None:
    from postpeer.types import CreateProfileBody

    with pytest.raises(ValidationError):
        CreateProfileBody(name="")
