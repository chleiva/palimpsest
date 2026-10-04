#!/usr/bin/env python3
"""Setting 3 data fetch — plain Python standard library, public CC0 Wikidata data, NO AWS/Bedrock.

Run from the repo root on a machine with ordinary internet access:
    python3 scripts/s3_fetch.py            (about 75 HTTP requests to wikidata.org; 2-5 minutes)
    python3 scripts/s3_fetch.py orgs       (second pass, after a first `build`: histories of the
                                            employer organisations, ~170 requests, 2-4 minutes)

It performs the three network stages of scripts/build_setting3.py in one go and writes the
responses in exactly the layout that `python3 scripts/build_setting3.py build OUTDIR` reads:
    bridge/responses/s3_select.json      SPARQL selection (<= 60 humans with employer history,
                                          an ended employer statement and a deprecated-rank statement)
    bridge/responses/s3_revlists.json    revision lists of the 40 sampled entities
    bridge/responses/s3_revcontent.json  content of <= 40 revisions sampled across each history
    bridge/data/s3/*.json                the fetched payloads (one file per URL / per revision)
    bridge/s3_qids.json, bridge/s3_revsample.json

Revision contents are fetched 50 revisions per request (the API maximum for non-bot users) and
split into one file per revision so that build_setting3.py needs no change. The script is
resumable: files that already exist are not fetched again. Requests carry a descriptive
User-Agent and are spaced 0.5 s apart, as the Wikimedia API etiquette asks.
"""
import json, os, random, sys, time, urllib.parse, urllib.request, zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
BR = os.path.join(ROOT, "bridge")
DATA = os.path.join(BR, "data", "s3")
RESP = os.path.join(BR, "responses")
UA = "palimpsest-research/0.1 (academic benchmark assembly; contact: chris@chrisgenai.com)"
PER_ENTITY, N_ENTITIES, BATCH = 40, 40, 50

from scripts.build_setting3 import SPARQL  # noqa: E402  (same selection query as the assembler)


def _get(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            if attempt == 3:
                raise
            print(f"  retry {attempt + 1} after error: {str(e)[:120]}", flush=True)
            time.sleep(5 * (attempt + 1))


def _fname(key):
    return os.path.join(DATA, f"{zlib.crc32(key.encode()):08x}.json")


def _fetch_to_file(url, key=None):
    """Fetch url into bridge/data/s3/<crc32>.json unless present; return the response entry."""
    key = key or url
    fn = _fname(key)
    if not os.path.exists(fn):
        raw = _get(url)
        json.loads(raw)                           # fail early on non-JSON (e.g. an HTML error page)
        open(fn, "wb").write(raw)
        time.sleep(0.5)
    return {"file": os.path.relpath(fn, ROOT), "bytes": os.path.getsize(fn)}


def _write_resp(name, mapping):
    os.makedirs(RESP, exist_ok=True)
    json.dump(mapping, open(os.path.join(RESP, name + ".json"), "w"), indent=1)
    print(f"wrote bridge/responses/{name}.json ({len(mapping)} entries)", flush=True)


def stage_select():
    url = "https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(SPARQL)
    print("1/3 SPARQL selection (may take up to a minute)...", flush=True)
    entry = _fetch_to_file(url, key="s3_select")
    _write_resp("s3_select", {url: entry})
    data = json.load(open(os.path.join(ROOT, entry["file"])))
    qids = [b["p"]["value"].rsplit("/", 1)[1] for b in data["results"]["bindings"]]
    print(f"  {len(qids)} candidate entities", flush=True)
    if not qids:
        sys.exit("SPARQL returned no entities; the query may have timed out — rerun, or report this.")
    return qids


def stage_revlists(qids):
    random.Random(0).shuffle(qids)
    qids = qids[:N_ENTITIES]
    json.dump(qids, open(os.path.join(BR, "s3_qids.json"), "w"))
    print(f"2/3 revision lists for {len(qids)} entities...", flush=True)
    mapping = {}
    for i, q in enumerate(qids):
        url = _revlist_url(q)
        mapping[url] = _fetch_to_file(url)
        if (i + 1) % 10 == 0:
            print(f"  {i + 1}/{len(qids)}", flush=True)
    _write_resp("s3_revlists", mapping)
    return mapping


def stage_revisions(revlists, sample_name="s3_revsample.json", resp_name="s3_revcontent"):
    sample = {}
    for url, entry in revlists.items():
        d = json.load(open(os.path.join(ROOT, entry["file"])))
        page = next(iter(d["query"]["pages"].values()))
        revs = page.get("revisions", [])
        if len(revs) > PER_ENTITY:
            idx = sorted(set(int(i * (len(revs) - 1) / (PER_ENTITY - 1)) for i in range(PER_ENTITY)))
            revs = [revs[i] for i in idx]
        sample[page["title"]] = [(rv["revid"], rv["timestamp"]) for rv in revs]
    json.dump(sample, open(os.path.join(BR, sample_name), "w"))
    rids = [rid for rs in sample.values() for rid, _ in rs]
    print(f"3/3 content of {len(rids)} revisions in batches of {BATCH}...", flush=True)
    mapping = {}
    pending = [rid for rid in rids if not os.path.exists(_fname(_single_url(rid)))]
    for i in range(0, len(pending), BATCH):
        chunk = pending[i:i + BATCH]
        url = ("https://www.wikidata.org/w/api.php?action=query&prop=revisions&revids=" + "|".join(map(str, chunk)) +
               "&rvprop=content|timestamp|ids&rvslots=main&format=json")
        d = json.loads(_get(url))
        time.sleep(0.5)
        for page in d.get("query", {}).get("pages", {}).values():
            for rv in page.get("revisions", []):
                single = {"query": {"pages": {str(page.get("pageid", 0)): {"pageid": page.get("pageid"), "ns": page.get("ns"),
                                                                              "title": page["title"], "revisions": [rv]}}}}
                json.dump(single, open(_fname(_single_url(rv["revid"])), "w"))
        print(f"  {min(i + BATCH, len(pending))}/{len(pending)}", flush=True)
    for rid in rids:
        u = _single_url(rid)
        fn = _fname(u)
        mapping[u] = {"file": os.path.relpath(fn, ROOT), "bytes": os.path.getsize(fn)} if os.path.exists(fn) else {"error": "missing (deleted or suppressed revision)"}
    _write_resp(resp_name, mapping)
    missing = sum(1 for v in mapping.values() if "error" in v)
    print(f"done: {len(mapping) - missing} revisions fetched, {missing} missing. Next: python3 scripts/build_setting3.py build data/setting3", flush=True)


def _single_url(rid):
    return (f"https://www.wikidata.org/w/api.php?action=query&prop=revisions&revids={rid}"
            f"&rvprop=content|timestamp|ids&rvslots=main&format=json")


def _revlist_url(q):
    return (f"https://www.wikidata.org/w/api.php?action=query&prop=revisions&titles={q}"
            f"&rvlimit=500&rvprop=ids|timestamp&format=json&rvdir=newer")


def stage_orgs(per_entity=15):
    """Second pass (run after `build` once): histories of the organisations that appear as
    employers in data/setting3, so that the derived employer -> hq_city -> work_city chain exists."""
    import glob
    listing = os.path.join(BR, "s3_org_qids.json")
    if os.path.exists(listing):                       # list written by a previous build (or supplied)
        orgs = json.load(open(listing))
    else:
        orgs = set()
        for f in glob.glob(os.path.join(ROOT, "data", "setting3", "s3_*.json")):
            if f.endswith(".gold.json") or f.endswith(".hidden.json"):
                continue
            for o in json.load(open(f))["observations"]:
                if o.get("attr") == "employer" and str(o.get("value", "")).startswith("Q"):
                    orgs.add(o["value"])
        orgs = sorted(orgs)
        json.dump(orgs, open(listing, "w"))
    print(f"orgs: revision lists for {len(orgs)} organisations...", flush=True)
    mapping = {}
    for i, q in enumerate(orgs):
        mapping[_revlist_url(q)] = _fetch_to_file(_revlist_url(q))
        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{len(orgs)}", flush=True)
    _write_resp("s3_org_revlists", mapping)
    global PER_ENTITY
    PER_ENTITY = per_entity
    stage_revisions(mapping, sample_name="s3_org_revsample.json", resp_name="s3_org_revcontent")


if __name__ == "__main__":
    os.makedirs(DATA, exist_ok=True)
    if sys.argv[1:] == ["orgs"]:
        stage_orgs()
    else:
        qids = stage_select()
        revlists = stage_revlists(qids)
        stage_revisions(revlists)
