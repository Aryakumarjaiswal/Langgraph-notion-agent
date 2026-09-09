"""Gemini chat wrapper using google.genai so thought_signature is kept for tools."""

from __future__ import annotations

import uuid
from typing import Any

from google import genai
from google.genai import types
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

SKIP_SIGNATURE = "skip_thought_signature_validator"
SIG_KEY = "__gemini_function_call_thought_signatures__"


VALID_SCHEMA_TYPES = {
    "string",
    "number",
    "integer",
    "boolean",
    "array",
    "object",
    "null",
}


def _clean_schema(schema: Any, depth: int = 0) -> Any:
    if depth > 3:
        return {"type": "object"}
    if isinstance(schema, list):
        return [_clean_schema(item, depth + 1) for item in schema[:4]]
    if not isinstance(schema, dict):
        return schema

    if "anyOf" in schema or "oneOf" in schema or "allOf" in schema:
        options = schema.get("anyOf") or schema.get("oneOf") or schema.get("allOf") or []
        first = next((item for item in options if isinstance(item, dict)), None)
        if first:
            merged = {k: v for k, v in schema.items() if k not in {"anyOf", "oneOf", "allOf"}}
            merged.update(first)
            return _clean_schema(merged, depth)

    cleaned: dict[str, Any] = {}
    for key, value in schema.items():
        if key in {"$schema", "title", "default", "$ref", "$defs", "definitions"}:
            continue
        if key == "additionalProperties":
            continue
        if key == "type":
            if isinstance(value, str) and value.lower() in VALID_SCHEMA_TYPES:
                cleaned["type"] = value.lower()
            elif isinstance(value, list):
                types_ok = [
                    item.lower()
                    for item in value
                    if isinstance(item, str) and item.lower() in VALID_SCHEMA_TYPES
                ]
                if types_ok:
                    cleaned["type"] = types_ok[0] if len(types_ok) == 1 else types_ok
            continue
        if key in {"anyOf", "oneOf", "allOf"} and isinstance(value, list) and value:
            cleaned[key] = [_clean_schema(item, depth + 1) for item in value[:4]]
            continue
        if isinstance(value, dict):
            cleaned[key] = _clean_schema(value, depth + 1)
        elif isinstance(value, list):
            cleaned[key] = [_clean_schema(item, depth + 1) for item in value[:12]]
        else:
            cleaned[key] = value

    if "properties" in cleaned and "type" not in cleaned:
        cleaned["type"] = "object"
    if "items" in cleaned and "type" not in cleaned:
        cleaned["type"] = "array"
    return cleaned


def _simple_object_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {}}


def _tools_to_genai(tools: list) -> list[types.Tool] | None:
    if not tools:
        return None
    decls = []
    for tool in tools:
        spec = convert_to_openai_tool(tool)["function"]
        raw = spec.get("parameters") or _simple_object_schema()
        try:
            parameters = _clean_schema(raw)
            decls.append(
                types.FunctionDeclaration(
                    name=spec["name"],
                    description=spec.get("description") or "",
                    parameters=parameters,
                )
            )
        except Exception:
            decls.append(
                types.FunctionDeclaration(
                    name=spec["name"],
                    description=spec.get("description") or "",
                    parameters=_simple_object_schema(),
                )
            )
    return [types.Tool(function_declarations=decls)]


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("text"):
                parts.append(str(block["text"]))
        return "".join(parts)
    return str(content or "")


class GeminiChat:
    def __init__(self, model: str, api_key: str, temperature: float = 0, tools: list | None = None):
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.tools = tools or []
        self.client = genai.Client(api_key=api_key)

    def bind_tools(self, tools: list) -> "GeminiChat":
        return GeminiChat(self.model, self.api_key, self.temperature, tools)

    def _contents_and_system(self, messages: list):
        system_text = ""
        contents: list[types.Content] = []
        pending_tools: list[ToolMessage] = [
            m for m in messages if isinstance(m, ToolMessage)
        ]
        used_tool_ids: set[str] = set()

        for message in messages:
            if isinstance(message, SystemMessage):
                system_text = (system_text + "\n" + _message_text(message.content)).strip()
            elif isinstance(message, HumanMessage):
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part(text=_message_text(message.content) or " ")],
                    )
                )
            elif isinstance(message, AIMessage):
                parts: list[types.Part] = []
                text = _message_text(message.content)
                if text:
                    parts.append(types.Part(text=text))
                sigs = list((message.additional_kwargs or {}).get(SIG_KEY) or [])
                for i, call in enumerate(message.tool_calls or []):
                    sig = sigs[i] if i < len(sigs) else SKIP_SIGNATURE
                    kwargs = {
                        "function_call": types.FunctionCall(
                            name=call["name"],
                            args=call.get("args") or {},
                        )
                    }
                    if sig:
                        kwargs["thought_signature"] = sig
                    parts.append(types.Part(**kwargs))
                if not parts:
                    parts.append(types.Part(text=" "))
                contents.append(types.Content(role="model", parts=parts))

                response_parts = []
                for call in message.tool_calls or []:
                    match = next(
                        (
                            t
                            for t in pending_tools
                            if t.tool_call_id == call.get("id") and t.tool_call_id not in used_tool_ids
                        ),
                        None,
                    )
                    if match is None:
                        continue
                    used_tool_ids.add(match.tool_call_id)
                    raw = match.content
                    if isinstance(raw, str):
                        payload = {"output": raw}
                    elif isinstance(raw, dict):
                        payload = raw
                    else:
                        payload = {"output": str(raw)}
                    response_parts.append(
                        types.Part(
                            function_response=types.FunctionResponse(
                                name=call["name"],
                                response=payload,
                            )
                        )
                    )
                if response_parts:
                    contents.append(types.Content(role="user", parts=response_parts))
        return system_text or None, contents

    async def ainvoke(self, messages: list) -> AIMessage:
        system_text, contents = self._contents_and_system(list(messages))
        config = types.GenerateContentConfig(
            temperature=self.temperature,
            tools=_tools_to_genai(self.tools),
            system_instruction=system_text,
        )
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=contents,
            config=config,
        )

        text_parts: list[str] = []
        tool_calls: list[dict] = []
        signatures: list[Any] = []
        parts = []
        if response.candidates and response.candidates[0].content:
            parts = response.candidates[0].content.parts or []
        for part in parts:
            if getattr(part, "function_call", None) and part.function_call:
                fc = part.function_call
                tool_calls.append(
                    {
                        "name": fc.name,
                        "args": dict(fc.args or {}),
                        "id": fc.id or str(uuid.uuid4()),
                    }
                )
                signatures.append(part.thought_signature or SKIP_SIGNATURE)
            elif getattr(part, "text", None):
                text_parts.append(part.text)

        return AIMessage(
            content="".join(text_parts),
            tool_calls=tool_calls,
            additional_kwargs={SIG_KEY: signatures} if signatures else {},
        )
