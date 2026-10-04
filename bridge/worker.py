#!/usr/bin/env python3
"""PALIMPSEST bridge worker (NOT needed for the released experiments; kept for completeness).

Status 3 Oct 2026: every LLM call in the paper went through nl/anthropic_client.py (Anthropic
Message Batches); the Setting 3 data fetch is done by scripts/s3_fetch.py (standard library,
no AWS). This worker was written for a Bedrock path that was never used. It is SAFE BY
DEFAULT: with "bedrock_enabled": false (the default, and the value in bridge/config.json) no
boto3 client is created, "chat" and "list_models" requests are refused, and only the
network-free/public "fetch" op (allow-listed hosts) is served. Note that "list_models", when
enabled, probes every accessible model with a 2-token call, which costs a few cents and is
NOT covered by the hard cap.

Polls <repo>/bridge/requests/*.json and writes <repo>/bridge/responses/<name>.json. Every call is logged to
bridge/ledger.jsonl with token counts and estimated cost; the worker refuses to start
a batch that would push cumulative estimated spend over the hard cap.

Request file format (JSON): {"op": "chat", "items": [{"id": str, "model": str, "system": str,
  "messages": [{"role": "user"|"assistant", "content": str}], "max_tokens": int, "temperature": float}]}
Other ops: {"op": "list_models"}, {"op": "fetch", "urls": [...]} (public data only, allow-listed hosts),
           {"op": "stop"}.

Start:  python3 bridge/worker.py            (from the repo root; needs boto3: python3 -m pip install boto3)
Stop:   create bridge/requests/stop.json with {"op": "stop"}, or Ctrl-C.
"""
import glob
import json
import os
import sys
import time
import threading
import traceback
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BR = os.path.join(ROOT, "bridge")
REQ, RESP, DATA = os.path.join(BR, "requests"), os.path.join(BR, "responses"), os.path.join(BR, "data")
LEDGER, STATUS = os.path.join(BR, "ledger.jsonl"), os.path.join(BR, "status.json")
CONFIG = os.path.join(BR, "config.json")

DEFAULT_CONFIG = {
    "bedrock_enabled": False,       # must be set to true explicitly before any Bedrock client is created
    "region": "us-east-1",
    "hard_cap_usd": 60.0,           # worker refuses to exceed this estimated spend
    "threads": 4,
    "poll_seconds": 3,
    # $ per 1M tokens (input, output). Entries are looked up by substring of the model id.
    "prices": {
        "nova-micro": [0.035, 0.14], "nova-lite": [0.06, 0.24], "nova-pro": [0.8, 3.2],
        "claude-haiku-4-5": [1.0, 5.0], "claude-3-5-haiku": [0.8, 4.0], "claude-3-haiku": [0.25, 1.25],
        "claude-sonnet-4": [3.0, 15.0], "claude-3-5-sonnet": [3.0, 15.0], "claude-3-7-sonnet": [3.0, 15.0],
        "llama3-1-8b": [0.22, 0.22], "llama3-2-3b": [0.15, 0.15], "llama3-2-1b": [0.1, 0.1], "llama3-3-70b": [0.72, 0.72],
        "mistral-7b": [0.15, 0.2], "mixtral-8x7b": [0.45, 0.7], "mistral-large": [2.0, 6.0],
        "titan-text-express": [0.2, 0.6], "titan-text-lite": [0.15, 0.2],
    },
    "fetch_allow_hosts": ["www.wikidata.org", "query.wikidata.org", "en.wikipedia.org", "huggingface.co",
                          "raw.githubusercontent.com", "github.com", "objects.githubusercontent.com", "cdn-lfs.huggingface.co"],
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG):
        cfg.update(json.load(open(CONFIG)))
    return cfg


def price_for(model_id, prices):
    m = model_id.lower()
    for k, v in prices.items():
        if k in m:
            return v
    return [5.0, 25.0]   # unknown model: assume expensive so the cap is conservative


def spent_so_far():
    tot = 0.0
    if os.path.exists(LEDGER):
        for line in open(LEDGER):
            try:
                tot += json.loads(line).get("cost_usd", 0.0)
            except Exception:
                pass
    return tot


def write_status(**kw):
    st = {"ts": datetime.now(timezone.utc).isoformat(), "spent_usd": round(spent_so_far(), 4), **kw}
    tmp = STATUS + ".tmp"
    json.dump(st, open(tmp, "w"), indent=1)
    os.replace(tmp, STATUS)


class Worker:
    def __init__(self):
        self.cfg = load_config()
        self.rt = self.ctl = None
        if self.cfg.get("bedrock_enabled"):
            import boto3
            self.rt = boto3.client("bedrock-runtime", region_name=self.cfg["region"])
            self.ctl = boto3.client("bedrock", region_name=self.cfg["region"])
        self.lock = threading.Lock()
        self.stop = False

    # ---------- ops ----------
    def op_list_models(self):
        if not self.ctl:
            return {"error": "refused: bedrock_enabled is false in bridge/config.json"}
        out = {"foundation_models": [], "inference_profiles": [], "errors": []}
        try:
            r = self.ctl.list_foundation_models()
            for m in r.get("modelSummaries", []):
                out["foundation_models"].append({"id": m["modelId"], "name": m.get("modelName"), "provider": m.get("providerName"),
                                                 "inference": m.get("inferenceTypesSupported"), "status": m.get("modelLifecycle", {}).get("status"),
                                                 "in": m.get("inputModalities"), "out": m.get("outputModalities")})
        except Exception as e:
            out["errors"].append(f"list_foundation_models: {e}")
        try:
            r = self.ctl.list_inference_profiles(maxResults=500)
            for p in r.get("inferenceProfileSummaries", []):
                out["inference_profiles"].append({"id": p["inferenceProfileId"], "name": p.get("inferenceProfileName"), "status": p.get("status"), "type": p.get("type")})
        except Exception as e:
            out["errors"].append(f"list_inference_profiles: {e}")
        # probe access: a 1-token call to each candidate text model id
        probes = {}
        for mid in [m["id"] for m in out["foundation_models"] if "TEXT" in (m["out"] or []) and "ON_DEMAND" in (m["inference"] or [])] + \
                   [p["id"] for p in out["inference_profiles"]]:
            try:
                self.rt.converse(modelId=mid, messages=[{"role": "user", "content": [{"text": "Say OK."}]}], inferenceConfig={"maxTokens": 2})
                probes[mid] = "ok"
            except Exception as e:
                probes[mid] = type(e).__name__ + ": " + str(e)[:120]
        out["probes"] = probes
        return out

    def op_fetch(self, urls):
        os.makedirs(DATA, exist_ok=True)
        res = {}
        for u in urls:
            host = u.split("/")[2]
            if host not in self.cfg["fetch_allow_hosts"]:
                res[u] = {"error": "host not allow-listed"}
                continue
            try:
                fn = os.path.join(DATA, f"{zlib.crc32(u.encode()):08x}.bin")   # deterministic across runs
                req = urllib.request.Request(u, headers={"User-Agent": "palimpsest-research/0.1 (contact: author)"})
                with urllib.request.urlopen(req, timeout=60) as r, open(fn, "wb") as f:
                    f.write(r.read())
                res[u] = {"file": os.path.relpath(fn, ROOT), "bytes": os.path.getsize(fn)}
            except Exception as e:
                res[u] = {"error": str(e)[:300]}
        return res

    def chat_one(self, item):
        model = item["model"]
        pin, pout = price_for(model, self.cfg["prices"])
        msgs = [{"role": m["role"], "content": [{"text": m["content"]}]} for m in item["messages"]]
        kw = {"modelId": model, "messages": msgs,
              "inferenceConfig": {"maxTokens": int(item.get("max_tokens", 512)), "temperature": float(item.get("temperature", 0.0))}}
        if item.get("system"):
            kw["system"] = [{"text": item["system"]}]
        delay = 2.0
        for attempt in range(6):
            try:
                t0 = time.time()
                r = self.rt.converse(**kw)
                u = r.get("usage", {})
                text = "".join(c.get("text", "") for c in r["output"]["message"]["content"])
                cost = (u.get("inputTokens", 0) * pin + u.get("outputTokens", 0) * pout) / 1e6
                rec = {"ts": datetime.now(timezone.utc).isoformat(), "id": item["id"], "model": model,
                       "in": u.get("inputTokens", 0), "out": u.get("outputTokens", 0), "cost_usd": round(cost, 6),
                       "latency_s": round(time.time() - t0, 2), "stop": r.get("stopReason")}
                with self.lock:
                    with open(LEDGER, "a") as f:
                        f.write(json.dumps(rec) + "\n")
                return {"id": item["id"], "text": text, "usage": rec}
            except Exception as e:
                name = type(e).__name__
                if "Throttling" in name or "Throttling" in str(e) or "ServiceUnavailable" in name or "ModelNotReady" in str(e):
                    time.sleep(delay); delay = min(delay * 2, 30)
                    continue
                return {"id": item["id"], "error": f"{name}: {str(e)[:300]}"}
        return {"id": item["id"], "error": "throttled after retries"}

    def op_chat(self, items):
        if not self.rt:
            return {"error": "refused: bedrock_enabled is false in bridge/config.json", "items": []}
        # pre-flight cost estimate (4 chars/token) against the cap
        est = 0.0
        for it in items:
            pin, pout = price_for(it["model"], self.cfg["prices"])
            chars = len(it.get("system", "")) + sum(len(m["content"]) for m in it["messages"])
            est += (chars / 4 * pin + int(it.get("max_tokens", 512)) * pout) / 1e6
        if spent_so_far() + est > self.cfg["hard_cap_usd"]:
            return {"error": f"refused: estimated ${est:.2f} would exceed hard cap ${self.cfg['hard_cap_usd']} (spent ${spent_so_far():.2f})", "items": []}
        with ThreadPoolExecutor(max_workers=int(self.cfg["threads"])) as ex:
            results = list(ex.map(self.chat_one, items))
        return {"items": results, "estimated_usd_before": round(est, 4)}

    # ---------- loop ----------
    def run(self):
        os.makedirs(REQ, exist_ok=True); os.makedirs(RESP, exist_ok=True)
        print(f"[worker] region={self.cfg['region']} cap=${self.cfg['hard_cap_usd']} spent=${spent_so_far():.2f}", flush=True)
        write_status(state="idle")
        while not self.stop:
            files = sorted(glob.glob(os.path.join(REQ, "*.json")))
            if not files:
                write_status(state="idle")
                time.sleep(self.cfg["poll_seconds"])
                self.cfg = load_config()
                continue
            for fp in files:
                name = os.path.splitext(os.path.basename(fp))[0]
                out_fp = os.path.join(RESP, name + ".json")
                try:
                    req = json.load(open(fp))
                except Exception:
                    time.sleep(1)      # file may still be being written
                    continue
                write_status(state="busy", request=name)
                print(f"[worker] {name}: op={req.get('op')} n={len(req.get('items', []))}", flush=True)
                try:
                    if req.get("op") == "stop":
                        self.stop = True; result = {"stopped": True}
                    elif req.get("op") == "list_models":
                        result = self.op_list_models()
                    elif req.get("op") == "fetch":
                        result = self.op_fetch(req.get("urls", []))
                    else:
                        result = self.op_chat(req.get("items", []))
                except Exception as e:
                    result = {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-2000:]}
                result["request"] = name
                result["spent_usd_total"] = round(spent_so_far(), 4)
                tmp = out_fp + ".tmp"
                json.dump(result, open(tmp, "w"), indent=1)
                os.replace(tmp, out_fp)
                os.remove(fp)
                print(f"[worker] {name}: done; spent so far ${spent_so_far():.2f}", flush=True)
        write_status(state="stopped")


if __name__ == "__main__":
    if load_config().get("bedrock_enabled"):
        try:
            import boto3  # noqa: F401
        except ImportError:
            print("boto3 missing: run  python3 -m pip install boto3", file=sys.stderr); sys.exit(1)
    else:
        print("[worker] bedrock_enabled=false: serving fetch requests only; chat/list_models are refused", flush=True)
    Worker().run()
