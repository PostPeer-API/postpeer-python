# Changelog

## 0.1.4

- Add comment listing, creation, replies, hiding, unhiding, and deletion on
  supported Facebook, Instagram, and Threads accounts.
- Add Instagram conversation listing, message retrieval, and DM replies.

## 0.1.3

- Add `connect.integrations.move(...)` for assigning an integration to a profile
  or leaving it unassigned.
- Expose integration authentication status and failure reasons so applications
  can prompt users to reconnect affected accounts.
- Add Instagram collaborator support for feed posts, carousels, and Reels.
- Match complete integration IDs in `connect.integrations.list(q=...)` searches.

## 0.1.2

- Add Facebook Page selection methods under `connect.facebook`.
- Add `connect.integrations.get(...)` for retrieving one integration.
- Add Twitter long-post support with
  `platformSpecificData={"longPost": true}`.

## 0.1.1

- Add `posts.scheduled.edit(...)` to replace a scheduled post's content, media,
  platforms, and optional scheduled time.
- Add Instagram Story support with
  `platformSpecificData={"contentType": "story"}`.
- Add LinkedIn organization mentions generated from the latest OpenAPI schema.

## 0.1.0

- Initial official PostPeer Python SDK.
- Synchronous and asynchronous HTTPX clients.
- OpenAPI-generated Pydantic models and resource methods.
