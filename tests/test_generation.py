from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import get_type_hints

import pytest

from postpeer import AsyncPostPeer, PostPeer
from scripts.generate_resources import OPERATION_PATHS, load_operations

ROOT = Path(__file__).resolve().parents[1]


def test_every_openapi_operation_has_one_resource_mapping() -> None:
    operations = load_operations(json.loads((ROOT / "openapi.json").read_text()))

    assert len(operations) == 39
    assert {operation.operation_id for operation in operations} == set(OPERATION_PATHS)
    assert len({operation.resource_path for operation in operations}) == 39


@pytest.mark.asyncio
async def test_every_operation_has_sync_async_signature_parity() -> None:
    sync = PostPeer(api_key="test")
    asynchronous = AsyncPostPeer(api_key="test")

    for resource_path in OPERATION_PATHS.values():
        sync_method: object = sync
        async_method: object = asynchronous
        for part in resource_path:
            sync_method = getattr(sync_method, part)
            async_method = getattr(async_method, part)

        assert callable(sync_method)
        assert callable(async_method)
        assert inspect.signature(sync_method) == inspect.signature(async_method)
        assert inspect.iscoroutinefunction(async_method)
        assert "_request_options" in inspect.signature(sync_method).parameters
        get_type_hints(sync_method)
        get_type_hints(async_method)

    sync.close()
    await asynchronous.aclose()


def test_generator_rejects_unmapped_operation() -> None:
    spec = {
        "paths": {
            "/example": {
                "get": {
                    "operationId": "unmappedOperation",
                    "responses": {"200": {"content": {"application/json": {"schema": {}}}}},
                }
            }
        }
    }

    with pytest.raises(ValueError, match="missing resource path mapping"):
        load_operations(spec)
