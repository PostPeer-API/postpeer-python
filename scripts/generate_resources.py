#!/usr/bin/env python3
"""Generate PostPeer's typed sync and async resource trees from OpenAPI."""

from __future__ import annotations

import json
import keyword
import py_compile
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "openapi.json"
OUTPUT_PATH = ROOT / "src/postpeer/resources/_generated.py"
MODELS_PATH = ROOT / "src/postpeer/_generated/pydantic_gen.py"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}

# This is the cross-language public SDK contract. Keep it aligned with
# ../postpeer-node/openapi-ts.config.ts.
OPERATION_PATHS: dict[str, tuple[str, ...]] = {
    "healthCheck": ("health", "check"),
    "healthCheckAuth": ("health", "verify_access_key"),
    "getLinkedInSelection": ("connect", "linkedin", "get_selection"),
    "submitLinkedInSelection": ("connect", "linkedin", "submit_selection"),
    "getFacebookSelection": ("connect", "facebook", "get_selection"),
    "submitFacebookSelection": ("connect", "facebook", "submit_selection"),
    "getOAuthUrl": ("connect", "get_oauth_url"),
    "connectBluesky": ("connect", "bluesky"),
    "listIntegrations": ("connect", "integrations", "list"),
    "getIntegration": ("connect", "integrations", "get"),
    "moveIntegration": ("connect", "integrations", "move"),
    "disconnectIntegration": ("connect", "integrations", "disconnect"),
    "createProfile": ("profiles", "create"),
    "listProfiles": ("profiles", "list"),
    "getProfile": ("profiles", "get"),
    "updateProfile": ("profiles", "update"),
    "deleteProfile": ("profiles", "delete"),
    "createApp": ("apps", "create"),
    "listApps": ("apps", "list"),
    "getApp": ("apps", "get"),
    "updateApp": ("apps", "update"),
    "deleteApp": ("apps", "delete"),
    "testNotification": ("notifications", "test"),
    "createNotification": ("notifications", "create"),
    "listNotifications": ("notifications", "list"),
    "getNotification": ("notifications", "get"),
    "updateNotification": ("notifications", "update"),
    "deleteNotification": ("notifications", "delete"),
    "listPlatforms": ("platforms", "list"),
    "createPost": ("posts", "create"),
    "listPosts": ("posts", "list"),
    "getPost": ("posts", "get"),
    "deletePost": ("posts", "delete"),
    "listScheduledPosts": ("posts", "scheduled", "list"),
    "editScheduledPost": ("posts", "scheduled", "edit"),
    "cancelScheduledPost": ("posts", "scheduled", "cancel"),
    "reschedulePost": ("posts", "scheduled", "reschedule"),
    "createMediaUpload": ("media", "upload"),
    "getAnalytics": ("analytics", "get"),
    "getUsage": ("usage", "get"),
    "getPinterestBoards": ("pinterest", "get_boards"),
    "getTikTokCreatorInfo": ("tiktok", "get_creator_info"),
    "aiWriteContent": ("ai", "write"),
    "aiGenerateImage": ("ai", "generate_image"),
}

# The API currently omits a success response for this operation. Keeping this
# exception explicit ensures any other missing success response fails generation.
RESPONSELESS_OPERATIONS = {"connectBluesky"}


@dataclass
class Parameter:
    python_name: str
    wire_name: str
    location: str
    annotation: str
    required: bool


@dataclass
class Operation:
    operation_id: str
    method: str
    url: str
    resource_path: tuple[str, ...]
    summary: str
    parameters: list[Parameter]
    body_model: str | None
    query_model: str | None
    path_model: str | None
    response_model: str | None


@dataclass
class ResourceNode:
    path: tuple[str, ...]
    operations: list[Operation] = field(default_factory=list)
    children: dict[str, ResourceNode] = field(default_factory=dict)


def snake_case(value: str) -> str:
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    value = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    if keyword.iskeyword(value):
        value += "_"
    return value


def pascal_case(value: str) -> str:
    return "".join(
        part[:1].upper() + part[1:] for part in re.split(r"[^a-zA-Z0-9]+", snake_case(value))
    )


def annotation_for(schema: dict[str, Any], *, generated_name: str | None = None) -> str:
    if schema.get("nullable"):
        non_nullable = {key: value for key, value in schema.items() if key != "nullable"}
        return f"{annotation_for(non_nullable, generated_name=generated_name)} | None"
    if "$ref" in schema:
        return f"models.{schema['$ref'].rsplit('/', 1)[-1]}"
    alternatives = schema.get("oneOf") or schema.get("anyOf")
    if alternatives:
        if generated_name is None:
            raise ValueError("inline unions require a generated model name")
        annotations: list[str] = []
        for index, alternative in enumerate(alternatives):
            alternative_name = (
                generated_name if index == 0 else f"{generated_name}_{'' if index == 1 else index}"
            )
            annotations.append(annotation_for(alternative, generated_name=alternative_name))
        return " | ".join(annotations)
    schema_type = schema.get("type")
    if schema_type == "null":
        return "None"
    if schema_type == "string":
        if schema.get("enum") and generated_name:
            return f"models.{generated_name} | str"
        return "str"
    if schema_type == "integer":
        return "int"
    if schema_type == "number":
        return "float"
    if schema_type == "boolean":
        return "bool"
    if schema_type == "array":
        item = schema.get("items", {})
        if not item:
            raise ValueError("array schema is missing items")
        item_annotation = annotation_for(item, generated_name=generated_name)
        return f"Sequence[{item_annotation}]"
    if schema_type == "object":
        if generated_name:
            return f"models.{generated_name} | Mapping[str, Any]"
        return "Mapping[str, Any]"
    raise ValueError(f"unsupported schema: {schema!r}")


def operation_parameters(
    path_item: dict[str, Any], operation: dict[str, Any]
) -> tuple[list[Parameter], str | None, str | None, str | None]:
    operation_id = operation["operationId"]
    prefix = pascal_case(operation_id)
    parameters: list[Parameter] = []
    seen: dict[str, tuple[str, str]] = {}

    for raw in [*(path_item.get("parameters") or []), *(operation.get("parameters") or [])]:
        location = raw["in"]
        if location not in {"path", "query", "header"}:
            raise ValueError(f"{operation_id}: unsupported parameter location {location!r}")
        wire_name = raw["name"]
        python_name = snake_case(wire_name)
        if python_name in seen:
            other_location, other_wire = seen[python_name]
            raise ValueError(
                f"{operation_id}: {other_location} {other_wire!r} and {location} "
                f"{wire_name!r} both map to {python_name!r}"
            )
        seen[python_name] = (location, wire_name)
        parameters.append(
            Parameter(
                python_name,
                wire_name,
                location,
                annotation_for(
                    raw.get("schema", {}),
                    generated_name=f"{prefix}{pascal_case(wire_name)}",
                ),
                bool(raw.get("required")),
            )
        )

    body_model: str | None = None
    request_body = operation.get("requestBody")
    if request_body:
        content = request_body.get("content", {})
        if set(content) - {"application/json"}:
            raise ValueError(f"{operation_id}: only application/json request bodies are supported")
        schema = content.get("application/json", {}).get("schema")
        if not schema:
            raise ValueError(f"{operation_id}: request body is missing a JSON schema")
        if schema.get("type") != "object" or "properties" not in schema:
            raise ValueError(f"{operation_id}: request body must be an inline object")
        body_model = f"{prefix}Body"
        required_fields = set(schema.get("required", []))
        for wire_name, property_schema in schema["properties"].items():
            python_name = snake_case(wire_name)
            if python_name in seen:
                other_location, other_wire = seen[python_name]
                raise ValueError(
                    f"{operation_id}: {other_location} {other_wire!r} and body "
                    f"{wire_name!r} both map to {python_name!r}"
                )
            seen[python_name] = ("body", wire_name)
            parameters.append(
                Parameter(
                    python_name,
                    wire_name,
                    "body",
                    annotation_for(
                        property_schema,
                        generated_name=f"{prefix}{pascal_case(wire_name)}",
                    ),
                    wire_name in required_fields,
                )
            )

    query_model = f"{prefix}Query" if any(p.location == "query" for p in parameters) else None
    path_model = f"{prefix}Path" if any(p.location == "path" for p in parameters) else None
    return parameters, body_model, query_model, path_model


def success_model(operation_id: str, operation: dict[str, Any]) -> str | None:
    successes = [
        response
        for status, response in operation.get("responses", {}).items()
        if status.isdigit() and 200 <= int(status) < 300
    ]
    if not successes:
        if operation_id in RESPONSELESS_OPERATIONS:
            return None
        raise ValueError(f"{operation_id}: missing a 2xx success response")
    schemas = [
        response.get("content", {}).get("application/json", {}).get("schema")
        for response in successes
    ]
    if not any(schemas):
        return None
    return f"{pascal_case(operation_id)}Response"


def load_operations(spec: dict[str, Any]) -> list[Operation]:
    operations: list[Operation] = []
    discovered: set[str] = set()
    for url, path_item in spec.get("paths", {}).items():
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            operation_id = operation.get("operationId")
            if not operation_id:
                raise ValueError(f"{method.upper()} {url}: missing operationId")
            if operation_id in discovered:
                raise ValueError(f"duplicate operationId: {operation_id}")
            discovered.add(operation_id)
            resource_path = OPERATION_PATHS.get(operation_id)
            if resource_path is None:
                raise ValueError(f"{operation_id}: missing resource path mapping")
            parameters, body_model, query_model, path_model = operation_parameters(
                path_item, operation
            )
            operations.append(
                Operation(
                    operation_id=operation_id,
                    method=method.upper(),
                    url=url,
                    resource_path=resource_path,
                    summary=operation.get("summary", operation_id),
                    parameters=parameters,
                    body_model=body_model,
                    query_model=query_model,
                    path_model=path_model,
                    response_model=success_model(operation_id, operation),
                )
            )

    stale = set(OPERATION_PATHS) - discovered
    if stale:
        raise ValueError(f"resource mappings without operations: {', '.join(sorted(stale))}")
    return operations


def build_tree(operations: list[Operation]) -> ResourceNode:
    root = ResourceNode(())
    for operation in operations:
        node = root
        for segment in operation.resource_path[:-1]:
            node = node.children.setdefault(segment, ResourceNode((*node.path, segment)))
        node.operations.append(operation)
    return root


def class_name(mode: str, path: tuple[str, ...]) -> str:
    if not path:
        return f"{mode}PostPeerResources"
    return f"{mode}{''.join(pascal_case(part) for part in path)}Resource"


def dict_literal(parameters: list[Parameter], location: str) -> str:
    values = [
        f"{parameter.wire_name!r}: {parameter.python_name}"
        for parameter in parameters
        if parameter.location == location
    ]
    return "{" + ", ".join(values) + "}"


def emit_method(operation: Operation, *, asynchronous: bool) -> list[str]:
    required = [parameter for parameter in operation.parameters if parameter.required]
    optional = [parameter for parameter in operation.parameters if not parameter.required]
    args = ["self"]
    args.extend(f"{parameter.python_name}: {parameter.annotation}" for parameter in required)
    if optional or True:
        args.append("*")
    args.extend(
        f"{parameter.python_name}: {parameter.annotation} | None = None" for parameter in optional
    )
    args.append("_request_options: RequestOptions | None = None")
    return_type = f"models.{operation.response_model}" if operation.response_model else "None"
    prefix = "async " if asynchronous else ""
    await_prefix = "await " if asynchronous else ""
    lines = [
        f"    {prefix}def {operation.resource_path[-1]}(",
        *(f"        {argument}," for argument in args),
        f"    ) -> {return_type}:",
        f'        """{operation.summary.replace(chr(34), chr(39))}"""',
    ]

    if operation.path_model:
        lines.extend(
            [
                f"        path_values = models.{operation.path_model}.model_validate(",
                f"            {dict_literal(operation.parameters, 'path')}",
                '        ).model_dump(mode="json", by_alias=True, exclude_none=True)',
                f"        path = {operation.url!r}",
            ]
        )
        for parameter in operation.parameters:
            if parameter.location == "path":
                placeholder = "{" + parameter.wire_name + "}"
                lines.append(
                    f"        path = path.replace({placeholder!r}, "
                    f"quote(str(path_values[{parameter.wire_name!r}]), safe=''))"
                )
    else:
        lines.append(f"        path = {operation.url!r}")

    if operation.query_model:
        lines.extend(
            [
                f"        query = models.{operation.query_model}.model_validate(",
                f"            {dict_literal(operation.parameters, 'query')}",
                '        ).model_dump(mode="json", by_alias=True, exclude_none=True)',
            ]
        )
    else:
        lines.append("        query = None")

    if operation.body_model:
        lines.extend(
            [
                f"        body = models.{operation.body_model}.model_validate(",
                f"            {dict_literal(operation.parameters, 'body')}",
                '        ).model_dump(mode="json", by_alias=True, exclude_none=True)',
            ]
        )
        for parameter in operation.parameters:
            if (
                parameter.location == "body"
                and parameter.required
                and "None" in parameter.annotation
            ):
                lines.extend(
                    [
                        f"        if {parameter.python_name} is None:",
                        f"            body[{parameter.wire_name!r}] = None",
                    ]
                )
    else:
        lines.append("        body = None")

    response_model = f"models.{operation.response_model}" if operation.response_model else "None"
    lines.extend(
        [
            f"        return {await_prefix}self._transport.request(",
            f"            {operation.method!r},",
            "            path,",
            f"            response_model={response_model},",
            "            query=query,",
            "            body=body,",
            "            options=_request_options,",
            "        )",
            "",
        ]
    )
    return lines


def walk_postorder(node: ResourceNode) -> list[ResourceNode]:
    result: list[ResourceNode] = []
    for child in node.children.values():
        result.extend(walk_postorder(child))
    result.append(node)
    return result


def emit_mode(root: ResourceNode, mode: str) -> list[str]:
    asynchronous = mode == "Async"
    base = "_AsyncResource" if asynchronous else "_SyncResource"
    lines: list[str] = []
    for node in walk_postorder(root):
        lines.extend([f"class {class_name(mode, node.path)}({base}):"])
        if not node.operations and not node.children:
            lines.append("    pass")
        for operation in sorted(node.operations, key=lambda item: item.resource_path[-1]):
            lines.extend(emit_method(operation, asynchronous=asynchronous))
        for name, child in sorted(node.children.items()):
            lines.extend(
                [
                    "    @cached_property",
                    f"    def {name}(self) -> {class_name(mode, child.path)}:",
                    f"        return {class_name(mode, child.path)}(self._transport)",
                    "",
                ]
            )
        lines.append("")
    return lines


def render(operations: list[Operation]) -> str:
    root = build_tree(operations)
    lines = [
        "# This file is auto-generated by scripts/generate_resources.py.",
        "# Do not edit this file directly.",
        "",
        "from __future__ import annotations",
        "",
        "from collections.abc import Mapping, Sequence",
        "from functools import cached_property",
        "from typing import Any",
        "from urllib.parse import quote",
        "",
        "from .._generated import pydantic_gen as models",
        "from .._transport import AsyncTransport, RequestOptions, SyncTransport",
        "",
        "",
        "class _SyncResource:",
        "    def __init__(self, transport: SyncTransport) -> None:",
        "        self._transport = transport",
        "",
        "",
        "class _AsyncResource:",
        "    def __init__(self, transport: AsyncTransport) -> None:",
        "        self._transport = transport",
        "",
        "",
    ]
    lines.extend(emit_mode(root, "Sync"))
    lines.extend(emit_mode(root, "Async"))
    lines.extend(
        [
            "__all__ = ['AsyncPostPeerResources', 'SyncPostPeerResources']",
            "",
        ]
    )
    return "\n".join(lines)


def postprocess_models() -> None:
    if not MODELS_PATH.exists():
        raise FileNotFoundError(
            f"{MODELS_PATH.relative_to(ROOT)} is missing; run the Hey API model generator first"
        )
    source = MODELS_PATH.read_text()
    # Hey API 0.0.24 does not prefix enum members whose normalized value starts
    # with a digit (for example, `3D_RENDER`). Prefix only those declarations.
    source = re.sub(r"^(\s+)([0-9][A-Z0-9_]*)\s*=", r"\1_\2 =", source, flags=re.MULTILINE)
    MODELS_PATH.write_text(source)
    py_compile.compile(str(MODELS_PATH), doraise=True)


def main() -> None:
    postprocess_models()
    spec = json.loads(SPEC_PATH.read_text())
    operations = load_operations(spec)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(render(operations))
    py_compile.compile(str(OUTPUT_PATH), doraise=True)
    print(f"Generated {OUTPUT_PATH.relative_to(ROOT)} from {len(operations)} operations")


if __name__ == "__main__":
    main()
