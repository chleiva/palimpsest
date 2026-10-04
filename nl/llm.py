"""LLM client interface: MockClient (deterministic, free) and BridgeClient (file bridge
served by bridge/worker.py on the Mac host, which calls Amazon Bedrock).

A client takes a list of requests [{"id", "system", "messages", "max_tokens", "temperature"}]
and returns {id: {"text": ..., "usage": {...}} or {"error": ...}}. Every call is
batched: one request file per stage, so that the bridge round-trip is amortised.
"""
from __future__ import annotations

import glob
import json
import os
import time
from typing import Callable, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.path.join(ROOT, "bridge")


class MockClient:
    """Answers come from a handler(request) -> text. Counts tokens as chars/4."""

    def __init__(self, handler: Callable[[dict], str], model: str = "mock"):
        self.handler, self.model = handler, model
        self.ledger: List[dict] = []

    def chat(self, items: List[dict], tag: str = "") -> Dict[str, dict]:
        out = {}
        for it in items:
            text = self.handler(it)
            chars_in = len(it.get("system", "")) + sum(len(m["content"]) for m in it["messages"])
            u = {"in": chars_in // 4, "out": len(text) // 4, "cost_usd": 0.0, "model": self.model}
            self.ledger.append({"id": it["id"], **u})
            out[it["id"]] = {"text": text, "usage": u}
        return out


class PendingResponse(Exception):
    """Raised by a non-blocking BridgeClient when the request has been written but the
    response is not there yet; re-run the stage once it is."""


class BridgeClient:
    """Writes bridge/requests/<tag>.json and reads bridge/responses/<tag>.json.
    blocking=True polls (use on a machine that shares the folder with the worker);
    blocking=False raises PendingResponse so the caller can ship the request file to the
    worker's machine and re-run later (every stage is resumable from disk)."""

    def __init__(self, model: str, poll: float = 5.0, timeout: float = 3600.0, blocking: bool = True):
        self.model, self.poll, self.timeout, self.blocking = model, poll, timeout, blocking
        os.makedirs(os.path.join(BRIDGE, "requests"), exist_ok=True)
        os.makedirs(os.path.join(BRIDGE, "responses"), exist_ok=True)

    def chat(self, items: List[dict], tag: str = "") -> Dict[str, dict]:
        tag = tag or f"req_{int(time.time())}"
        resp_fp = os.path.join(BRIDGE, "responses", tag + ".json")
        if not os.path.exists(resp_fp):                # resumable: reuse an existing response
            for it in items:
                it.setdefault("model", self.model)
            req_fp = os.path.join(BRIDGE, "requests", tag + ".json")
            if not os.path.exists(req_fp):
                tmp = req_fp + ".tmp"
                json.dump({"op": "chat", "items": items}, open(tmp, "w"))
                os.replace(tmp, req_fp)
            if not self.blocking:
                raise PendingResponse(tag)
            t0 = time.time()
            while not os.path.exists(resp_fp):
                if time.time() - t0 > self.timeout:
                    raise TimeoutError(f"bridge response {tag} not received")
                time.sleep(self.poll)
        r = json.load(open(resp_fp))
        if "error" in r and not r.get("items"):
            raise RuntimeError(r["error"])
        out = {}
        for x in r["items"]:
            out[x["id"]] = {"text": x.get("text", ""), "usage": x.get("usage", {}), "error": x.get("error")}
        return out


def extract_json(text: str) -> Optional[dict]:
    """Pull the first JSON object out of a model reply (tolerates code fences and prose)."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None
