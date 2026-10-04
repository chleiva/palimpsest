"""RQ2 corruption curve (free): mock extractor with injected error rates on the Setting 2
streams; reports warranted downstream accuracy (and other endpoints) for PALIMPSEST,
no-propagation and the temporal DB as a function of slot-error and missed-cue rates."""
import json, os, sys, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.run_setting2 import mock_clients, summarise
from nl.pipeline import Setting2, load_streams

GRID = [("slot_error", r) for r in (0.0, 0.05, 0.10, 0.20, 0.35)] + [("missed_cue", r) for r in (0.10, 0.25, 0.50)] + [("spurious_cue", r) for r in (0.05, 0.15)] + [("missed_valid", r) for r in (0.25, 0.5)]

def main(datadir, out, limit=50):
    streams = load_streams(datadir, limit)
    rows = []
    for kind, rate in GRID:
        od = f"{out}/{kind}_{rate}"
        shutil.rmtree(od, ignore_errors=True)
        cheap, backbone = mock_clients(streams, {kind: rate})
        pl = Setting2(od, cheap, backbone)
        for st in ("render", "paraphrase", "cuecheck", "extract"):
            getattr(pl, st)(streams)
        pl.run_systems(streams, with_llm_log=False, with_nl_log=False)
        res = pl.score(streams); rep = summarise(res)
        row = {"kind": kind, "rate": rate, "extraction": rep["_extraction"]}
        for sysn in ("palimpsest", "palimpsest_noprop", "temporal_db", "always_commit"):
            row[sysn] = {k: rep[sysn][k][0] for k in ("warranted_acc", "resolvable_acc", "unresolved_acc", "commit_rate", "unsupported_prop")}
            row[sysn + "_ci"] = {k: rep[sysn][k][1:] for k in ("warranted_acc", "resolvable_acc", "unresolved_acc", "commit_rate", "unsupported_prop")}   # stream-level cluster bootstrap
        rows.append(row)
        print(f"{kind}={rate}: PAL warr={row['palimpsest']['warranted_acc']:.3f} noprop={row['palimpsest_noprop']['warranted_acc']:.3f} tdb={row['temporal_db']['warranted_acc']:.3f} | PAL resolvable={row['palimpsest']['resolvable_acc']:.3f} unresolved={row['palimpsest']['unresolved_acc']:.3f}", flush=True)
        shutil.rmtree(od, ignore_errors=True)
    json.dump(rows, open(f"{out}/_noise_grid.json", "w"), indent=1)

if __name__ == "__main__":
    os.makedirs(sys.argv[2], exist_ok=True)
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 50)
