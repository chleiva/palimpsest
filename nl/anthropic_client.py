"""Anthropic Messages API client with the Message Batches API (50% off), prompt caching on
the system block, a cost ledger, and a hard spend cap. Non-blocking: a batch is submitted
once per tag and PendingResponse is raised until it has ended; results are cached on disk.

Key: read from $ANTHROPIC_API_KEY or ~/.secrets/anthropic_key (never stored in the repo).
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Dict, List

from nl.llm import PendingResponse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "data", "anthropic_batches")
LEDGER = os.path.join(ROOT, "data", "anthropic_ledger.jsonl")
API = "https://api.anthropic.com/v1"
VERSION = "2023-06-01"
# $ per 1M tokens: (input, output, cache_write_5m, cache_read); batch = 50% of these
PRICES = {
    "claude-haiku-4-5": (1.0, 5.0, 1.25, 0.10),
    "claude-sonnet-4-6": (3.0, 15.0, 3.75, 0.30),
    "claude-sonnet-4-5": (3.0, 15.0, 3.75, 0.30),
}


def _key() -> str:
    k = os.environ.get("ANTHROPIC_API_KEY")
    if not k:
        p = os.path.expanduser("~/.secrets/anthropic_key")
        k = open(p).read().strip()
    return k


def _price(model: str):
    for k, v in PRICES.items():
        if model.startswith(k):
            return v
    return (15.0, 75.0, 18.75, 1.5)   # unknown: assume expensive


def _call(method: str, path: str, body=None, raw=False):
    req = urllib.request.Request(API + path if path.startswith("/") else path, method=method)
    req.add_header("x-api-key", _key()); req.add_header("anthropic-version", VERSION); req.add_header("content-type", "application/json")
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data=data, timeout=120) as r:
        payload = r.read()
    return payload.decode() if raw else json.loads(payload)


def spent() -> float:
    tot = 0.0
    if os.path.exists(LEDGER):
        for line in open(LEDGER):
            try:
                tot += json.loads(line).get("cost_usd", 0.0)
            except Exception:
                pass
    return tot


class AnthropicBatchClient:
    def __init__(self, model: str, hard_cap_usd: float = 75.0, cache_system: bool = True, namespace: str = "default"):
        self.model, self.cap, self.cache_system = model, hard_cap_usd, cache_system
        self.state = os.path.join(STATE, namespace)        # batch state is namespaced per run directory
        os.makedirs(self.state, exist_ok=True); os.makedirs(os.path.dirname(LEDGER), exist_ok=True)

    def _params(self, it: dict) -> dict:
        p = {"model": it.get("model") or self.model, "max_tokens": int(it.get("max_tokens", 512)),
             "temperature": float(it.get("temperature", 0.0)), "messages": it["messages"]}
        if it.get("system"):
            p["system"] = [{"type": "text", "text": it["system"], **({"cache_control": {"type": "ephemeral"}} if self.cache_system else {})}]
        return p

    def _estimate(self, items: List[dict]) -> float:
        est = 0.0
        for it in items:
            pin, pout, _, _ = _price(it.get("model") or self.model)
            chars = len(it.get("system", "")) + sum(len(m["content"]) for m in it["messages"])
            est += 0.5 * (chars / 4 * pin + int(it.get("max_tokens", 512)) * 0.4 * pout) / 1e6   # batch price, ~40% of max_tokens used
        return est

    def chat(self, items: List[dict], tag: str = "") -> Dict[str, dict]:
        res_fp = os.path.join(self.state, tag + ".results.json")
        if os.path.exists(res_fp):
            return json.load(open(res_fp))
        st_fp = os.path.join(self.state, tag + ".batch.json")
        if not os.path.exists(st_fp):
            est = self._estimate(items)
            if spent() + est > self.cap:
                raise RuntimeError(f"refused batch {tag}: estimated ${est:.2f} + spent ${spent():.2f} exceeds cap ${self.cap}")
            reqs = [{"custom_id": _cid(it["id"]), "params": self._params(it)} for it in items]
            idmap = {_cid(it["id"]): it["id"] for it in items}
            out = {"batches": [], "idmap": idmap, "estimate_usd": est, "n": len(items)}
            for i in range(0, len(reqs), 10000):           # keep each batch well under the size limits
                b = _call("POST", "/messages/batches", {"requests": reqs[i:i + 10000]})
                out["batches"].append(b["id"])
                print(f"[anthropic] submitted batch {b['id']} ({len(reqs[i:i+10000])} requests) for {tag}; est ${est:.2f}", flush=True)
            json.dump(out, open(st_fp, "w"))
            raise PendingResponse(tag)
        st = json.load(open(st_fp))
        results: Dict[str, dict] = {}
        for bid in st["batches"]:
            b = _call("GET", f"/messages/batches/{bid}")
            if b.get("processing_status") != "ended":
                c = b.get("request_counts", {})
                print(f"[anthropic] batch {bid}: {b.get('processing_status')} {c}", flush=True)
                raise PendingResponse(tag)
            text = _call("GET", b["results_url"], raw=True)
            for line in text.splitlines():
                if not line.strip():
                    continue
                r = json.loads(line)
                rid = st["idmap"].get(r["custom_id"], r["custom_id"])
                res = r.get("result", {})
                if res.get("type") == "succeeded":
                    msg = res["message"]
                    u = msg.get("usage", {})
                    pin, pout, pcw, pcr = _price(msg.get("model", self.model))
                    cost = 0.5 * (u.get("input_tokens", 0) * pin + u.get("output_tokens", 0) * pout
                                  + u.get("cache_creation_input_tokens", 0) * pcw + u.get("cache_read_input_tokens", 0) * pcr) / 1e6
                    usage = {"in": u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0),
                             "out": u.get("output_tokens", 0), "cache_read": u.get("cache_read_input_tokens", 0), "cost_usd": round(cost, 6), "model": msg.get("model")}
                    results[rid] = {"text": "".join(c.get("text", "") for c in msg.get("content", []) if c.get("type") == "text"), "usage": usage}
                    with open(LEDGER, "a") as f:
                        f.write(json.dumps({"tag": tag, "id": rid, **usage}) + "\n")
                else:
                    results[rid] = {"text": "", "usage": {}, "error": json.dumps(res)[:300]}
        json.dump(results, open(res_fp, "w"))
        print(f"[anthropic] {tag}: {len(results)} results; spent so far ${spent():.2f}", flush=True)
        return results


def _cid(s: str) -> str:
    import re
    c = re.sub(r"[^a-zA-Z0-9_-]", "_", s)
    return c[:64]
