# PostPeer Python SDK

The official Python SDK for the [PostPeer API](https://postpeer.dev), generated
from PostPeer's OpenAPI contract with [Hey API](https://heyapi.dev/).

## Installation

```bash
pip install postpeer
```

Python 3.10 or newer is required.

## Quick start

```python
from postpeer import PostPeer

client = PostPeer()  # Reads POSTPEER_API_KEY

post = client.posts.create(
    content="Hello from PostPeer!",
    platforms=[{"platform": "twitter", "accountId": "integration-id"}],
    publish_now=True,
)

print(post.post_id)
client.close()
```

The client can also be used as a context manager:

```python
with PostPeer(api_key="your-access-key") as client:
    profiles = client.profiles.list()
```

## Async usage

`AsyncPostPeer` has the same resources and method names:

```python
import asyncio

from postpeer import AsyncPostPeer


async def main() -> None:
    async with AsyncPostPeer() as client:
        posts = await client.posts.list(status="scheduled")
        print(posts)


asyncio.run(main())
```

## Configuration

```python
import httpx

from postpeer import PostPeer

transport = httpx.Client(http2=True)
client = PostPeer(
    api_key="your-access-key",
    base_url="https://api.postpeer.dev",
    timeout=60.0,
    max_retries=2,
    default_headers={"X-Application": "my-app"},
    http_client=transport,
)
```

Each SDK instance is isolated. An injected HTTPX client remains owned by the
caller and is not closed by the SDK.

## Resources

The resource hierarchy matches the official Node.js SDK:

```python
client.health.check()
client.health.verify_access_key()

client.connect.get_oauth_url(platform="linkedin")
client.connect.facebook.get_selection(token="...")
client.connect.facebook.submit_selection(token="...", selected_account_ids=["..."])
client.connect.linkedin.get_selection(token="...")
client.connect.integrations.list()
client.connect.integrations.get(id="...")
client.connect.integrations.move(id="...", profile_id="...")

client.profiles.create(name="Marketing")
client.apps.list()
client.notifications.list()
client.platforms.list()

client.comments.list(platform="instagram", account_id="...", post_id="...")
client.comments.create(
    platform="instagram",
    account_id="...",
    post_id="...",
    text="Thanks!",
)
client.comments.hide(
    comment_id="...",
    platform="instagram",
    account_id="...",
    hidden=True,
)
client.comments.delete(platform="instagram", account_id="...", comment_id="...")

client.messages.list(platform="instagram", account_id="...")
client.messages.get(platform="instagram", account_id="...", conversation_id="...")
client.messages.send(
    platform="instagram",
    account_id="...",
    recipient_id="...",
    text="Hello!",
)

client.posts.create(content="Hello", platforms=[...], publish_now=True)
client.posts.list(status="scheduled")
client.posts.get(post_id="...")
client.posts.delete(post_id="...")
client.posts.scheduled.list()
client.posts.scheduled.edit(
    post_id="...",
    content="Updated content",
    platforms=[...],
)
client.posts.scheduled.cancel(post_id="...")

client.media.upload(filename="image.png", mime_type="image/png")
client.analytics.get()
client.usage.get()
client.pinterest.get_boards(account_id="...")
client.tiktok.get_creator_info(account_id="...")
client.ai.write(description="A launch announcement", platforms=["linkedin"])
```

Eligible X Premium accounts can opt into long posts with
`platformSpecificData={"longPost": True}` on the Twitter platform entry.

Instagram feed posts, carousels, and Reels can invite up to three collaborators
with `platformSpecificData={"collaborators": ["username"]}`.

Parameters use Python `snake_case`; the SDK serializes their OpenAPI aliases on
the wire. Responses are validated Pydantic v2 models. All generated models and
enums are available from `postpeer.types`.

## Errors

```python
from postpeer import NotFoundError, RateLimitError

try:
    client.posts.get(post_id="missing")
except NotFoundError as error:
    print(error.status, error.request_id, error.message)
except RateLimitError:
    print("PostPeer rate limit reached")
```

The SDK exports typed API, connection, timeout, and response-validation errors.

## Retries and request options

GET, PUT, and DELETE requests retry transient connection failures, 408, 409,
429, and 5xx responses by default. POST and PATCH are not automatically retried,
because replaying an ambiguous request could publish or create a resource twice.

Use `RequestOptions` for an explicit per-call override:

```python
from postpeer import RequestOptions

client.posts.create(
    content="Hello",
    platforms=[...],
    publish_now=True,
    _request_options=RequestOptions(
        timeout=30.0,
        max_retries=2,
        retry_non_idempotent=True,
    ),
)
```

## Updating generated code

The OpenAPI specification and package releases are intentionally separate:

```bash
pnpm spec:fetch
pnpm generate
uv run ruff format .
uv run ruff check .
uv run mypy
uv run pytest
```

`openapi.json`, `src/postpeer/_generated`, and
`src/postpeer/resources/_generated.py` must be committed together. Generated
files must not be edited manually.

Hey API 0.0.24 currently generates the Pydantic models. A deterministic
PostPeer-owned generator emits the sync and async resources until Hey API's
Python runtime is mature enough to replace it.

## Versioning

PostPeer uses conservative pre-1.0 versioning. Compatible additions remain in
`0.1.x`; a breaking SDK change moves to `0.2.0`; `1.0.0` is reserved for a
stable public contract.
