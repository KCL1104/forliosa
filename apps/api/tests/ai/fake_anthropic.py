"""A scripted fake of the Messages API behind the real ``anthropic`` SDK (httpx2 ``MockTransport``).

Each request pops the next scripted reply: a message (streamed as real SSE events when the request has
``stream: true``, JSON otherwise) or an HTTP error. Requests are recorded with the API key that sent them, so
tests can check key rotation, the exact request body (tools, cache_control, replayed history) and that no
network is used.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import anthropic
import httpx2

MODEL = "claude-haiku-5-5"


# -- content block helpers ---------------------------------------------------------------------------------
def text(t: str, citations: list[dict] | None = None) -> dict:
    b: dict[str, Any] = {"type": "text", "text": t}
    if citations:
        b["citations"] = citations
    return b


def thinking(signature: str = "sig-abc") -> dict:
    return {"type": "thinking", "thinking": "", "signature": signature}


def tool_use(tid: str, name: str, inp: dict) -> dict:
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def server_tool_use(tid: str, name: str, inp: dict) -> dict:
    return {"type": "server_tool_use", "id": tid, "name": name, "input": inp}


def web_search_result(tid: str, results: list[dict]) -> dict:
    return {"type": "web_search_tool_result", "tool_use_id": tid,
            "content": [{"type": "web_search_result", "page_age": None, **r} for r in results]}


def search_citation(url: str, title: str, cited: str) -> dict:
    return {"type": "web_search_result_location", "url": url, "title": title, "encrypted_index": "enc-idx",
            "cited_text": cited}


@dataclass
class Reply:
    blocks: list[dict] = field(default_factory=list)
    stop_reason: str = "end_turn"
    usage: dict[str, Any] = field(default_factory=dict)
    status: int = 200
    error_type: str | None = None
    fail_after_text: bool = False  # stream some text, then an SSE error event (mid-stream failure)
    stop_details: dict | None = None
    error_message: str = "scripted error"


def _sse(event: dict) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


def stream_body(reply: Reply, model: str) -> bytes:
    u = {"input_tokens": 100, "output_tokens": 20, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
         **reply.usage}
    out = [_sse({"type": "message_start", "message": {
        "id": "msg_fake", "type": "message", "role": "assistant", "model": model, "content": [],
        "stop_reason": None, "stop_sequence": None,
        "usage": {k: u[k] for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")}
        | {"output_tokens": 1}}})]
    for i, b in enumerate(reply.blocks):
        t = b["type"]
        if t == "text":
            out.append(_sse({"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}}))
            half = max(1, len(b["text"]) // 2)
            for chunk in (b["text"][:half], b["text"][half:]):
                if chunk:
                    out.append(_sse({"type": "content_block_delta", "index": i,
                                     "delta": {"type": "text_delta", "text": chunk}}))
            if reply.fail_after_text:
                out.append(_sse({"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}))
                return "".join(out).encode()
            for c in b.get("citations") or []:
                out.append(_sse({"type": "content_block_delta", "index": i,
                                 "delta": {"type": "citations_delta", "citation": c}}))
        elif t == "thinking":
            out.append(_sse({"type": "content_block_start", "index": i,
                             "content_block": {"type": "thinking", "thinking": "", "signature": ""}}))
            out.append(_sse({"type": "content_block_delta", "index": i,
                             "delta": {"type": "signature_delta", "signature": b["signature"]}}))
        elif t in ("tool_use", "server_tool_use"):
            out.append(_sse({"type": "content_block_start", "index": i,
                             "content_block": {"type": t, "id": b["id"], "name": b["name"], "input": {}}}))
            out.append(_sse({"type": "content_block_delta", "index": i,
                             "delta": {"type": "input_json_delta", "partial_json": json.dumps(b["input"])}}))
        else:  # result blocks arrive complete in content_block_start
            out.append(_sse({"type": "content_block_start", "index": i, "content_block": b}))
        out.append(_sse({"type": "content_block_stop", "index": i}))
    delta_usage: dict[str, Any] = {"output_tokens": u["output_tokens"]}
    if "server_tool_use" in u:
        delta_usage["server_tool_use"] = u["server_tool_use"]
    out.append(_sse({"type": "message_delta", "delta": {"stop_reason": reply.stop_reason, "stop_sequence": None,
                                                         **({"stop_details": reply.stop_details}
                                                            if reply.stop_details else {})},
                     "usage": delta_usage}))
    out.append(_sse({"type": "message_stop"}))
    return "".join(out).encode()


def json_body(reply: Reply, model: str) -> dict:
    u = {"input_tokens": 100, "output_tokens": 20, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
         **reply.usage}
    return {"id": "msg_fake", "type": "message", "role": "assistant", "model": model, "content": reply.blocks,
            "stop_reason": reply.stop_reason, "stop_sequence": None, "usage": u}


class FakeAnthropic:
    def __init__(self) -> None:
        self.script: deque[Reply] = deque()
        self.requests: list[dict[str, Any]] = []

    # scripting
    def reply(self, *blocks: dict, stop_reason: str = "end_turn", **kw: Any) -> FakeAnthropic:
        self.script.append(Reply(list(blocks), stop_reason, **kw))
        return self

    def error(self, status: int, error_type: str, message: str = "scripted error") -> FakeAnthropic:
        self.script.append(Reply(status=status, error_type=error_type, error_message=message))
        return self

    # transport
    def handler(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        key = request.headers.get("authorization", "").removeprefix("Bearer ")
        self.requests.append({"key": key, "body": body, "headers": dict(request.headers)})
        if not self.script:
            return httpx2.Response(500, json={"type": "error", "error": {"type": "api_error",
                                                                          "message": "fake: no scripted reply"}})
        reply = self.script.popleft()
        if reply.status != 200:
            return httpx2.Response(reply.status, json={"type": "error", "error": {"type": reply.error_type,
                                                                                  "message": reply.error_message}})
        model = body.get("model", MODEL)
        if body.get("stream"):
            return httpx2.Response(200, headers={"content-type": "text/event-stream"},
                                   content=stream_body(reply, model))
        return httpx2.Response(200, json=json_body(reply, model))

    def client(self, key: str) -> anthropic.Anthropic:
        return anthropic.Anthropic(api_key=key, max_retries=0,
                                   http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(self.handler)))

    @property
    def keys_used(self) -> list[str]:
        return [r["key"] for r in self.requests]
