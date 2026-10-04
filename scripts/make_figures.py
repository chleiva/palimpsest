"""Figures for the paper from cached result files (no LLM). Writes paper/figures/*.pdf.
  systems.pdf   CPU per stream and query latency: incremental maintenance vs symbolic replay vs query ratio (+ scale rows)
  noise.pdf     corruption curves with stream-level bootstrap bands (data/noise_grid/_noise_grid.json)
  regime.pdf    recency vs PALIMPSEST world accuracy per regime (bars), with abstention
"""
import json, os, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIG = os.path.join(ROOT, "paper", "figures")
os.makedirs(FIG, exist_ok=True)
plt.rcParams.update({"font.size": 8, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.alpha": 0.25, "grid.linewidth": 0.5,
                     "legend.frameon": False, "figure.dpi": 150, "savefig.bbox": "tight"})
C = {"incremental": "#1f4e79", "replay_cold": "#c0504d", "replay_lazy": "#e3a63b", "palimpsest": "#1f4e79", "palimpsest_noprop": "#7fa6cc", "temporal_db": "#c0504d", "always_commit": "#999999"}
LAB = {"incremental": "incremental store", "replay_cold": "symbolic replay (cold)", "replay_lazy": "symbolic replay (cached)", "palimpsest": "Palimpsest", "palimpsest_noprop": "no propagation", "temporal_db": "temporal DB (last write wins)", "always_commit": "always commit"}


def fig_systems():
    d = json.load(open(os.path.join(ROOT, "data", "systems_bench.json")))["summary"]
    ratios = sorted({float(k.split("r=")[1]) for k in d if k.startswith("setting1")})
    fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.2))
    for name in ("incremental", "replay_cold", "replay_lazy"):
        ys = [d[f"setting1|r={r}"][name]["cpu_total_s"] for r in ratios]
        axes[0].plot(ratios, ys, "o-", color=C[name], label=LAB[name], ms=3, lw=1.2)
    axes[0].set_xscale("log"); axes[0].set_xlabel("queries per observation $r$"); axes[0].set_ylabel("CPU s per stream"); axes[0].set_title("total work", fontsize=8)
    axes[0].legend(fontsize=6, loc="upper left")
    for name in ("incremental", "replay_cold"):
        ys = [d[f"setting1|r={r}"][name]["lat_mean_ms"] for r in ratios]; p95 = [d[f"setting1|r={r}"][name]["lat_p95_ms"] for r in ratios]
        axes[1].plot(ratios, ys, "o-", color=C[name], ms=3, lw=1.2, label=LAB[name] + " (mean)"); axes[1].plot(ratios, p95, "s--", color=C[name], ms=3, lw=0.9, label=LAB[name] + " (p95)")
    axes[1].set_xscale("log"); axes[1].set_yscale("log"); axes[1].set_xlabel("queries per observation $r$"); axes[1].set_ylabel("query latency, ms"); axes[1].set_title("latency", fontsize=8); axes[1].legend(fontsize=5.5)
    scale = [("scale_m7_T60|r=1.0", "m=7\nT=60"), ("scale_m10_T60|r=1.0", "m=10\nT=60"), ("scale_m13_T60|r=1.0", "m=13\nT=60"), ("scale_m7_T120|r=1.0", "m=7\nT=120"), ("scale_m7_T240|r=1.0", "m=7\nT=240")]
    xs = range(len(scale)); w = 0.38
    for i, name in enumerate(("incremental", "replay_cold")):
        axes[2].bar([x + (i - 0.5) * w for x in xs], [d[k][name]["cpu_total_s"] for k, _ in scale], w, color=C[name], label=LAB[name])
    axes[2].set_xticks(list(xs)); axes[2].set_xticklabels([l for _, l in scale], fontsize=6); axes[2].set_ylabel("CPU s per stream ($r=1$)"); axes[2].set_title("scale: reports per key $m$, horizon $T$", fontsize=8); axes[2].legend(fontsize=6)
    fig.savefig(os.path.join(FIG, "systems.pdf")); plt.close(fig)


def fig_noise():
    rows = json.load(open(os.path.join(ROOT, "data", "noise_grid", "_noise_grid.json")))
    kinds = [("slot_error", "wrong value rate"), ("missed_cue", "dropped change-cue rate"), ("spurious_cue", "added change-cue rate"), ("missed_valid", "dropped date rate")]
    fig, axes = plt.subplots(1, 4, figsize=(7.2, 2.0), sharey=True)
    for ax, (kind, xl) in zip(axes, kinds):
        rs = sorted({r["rate"] for r in rows if r["kind"] == kind} | ({0.0} if kind != "slot_error" else set()))
        base = next(r for r in rows if r["kind"] == "slot_error" and r["rate"] == 0.0)
        for name in ("palimpsest", "palimpsest_noprop", "temporal_db", "always_commit"):
            ys, lo, hi = [], [], []
            for rate in rs:
                r = base if rate == 0.0 else next(x for x in rows if x["kind"] == kind and x["rate"] == rate)
                ys.append(r[name]["warranted_acc"])
                ci = r.get(name + "_ci", {}).get("warranted_acc")
                lo.append(ci[0] if ci else r[name]["warranted_acc"]); hi.append(ci[1] if ci else r[name]["warranted_acc"])
            ax.plot(rs, ys, "o-", color=C[name], ms=2.5, lw=1.1, label=LAB[name]); ax.fill_between(rs, lo, hi, color=C[name], alpha=0.15, lw=0)
        ax.set_xlabel(xl); ax.set_ylim(0, 1.02)
        if kind == "slot_error":
            ax.axvspan(0.003, 0.015, color="#444444", alpha=0.12, lw=0); ax.text(0.016, 0.05, "measured\nextractors", fontsize=5.5, color="#444444")
    axes[0].set_ylabel("warranted downstream accuracy"); axes[0].legend(fontsize=5.5, loc="lower left")
    fig.savefig(os.path.join(FIG, "noise.pdf")); plt.close(fig)


def fig_regime():
    d = json.load(open(os.path.join(ROOT, "data", "regime_fresh_P0c.json"))); p = json.load(open(os.path.join(ROOT, "data", "regime_table_poison.json")))
    regs = [("self_update", "self-\nupdate"), ("multi_source_update", "multi-source\nupdate"), ("stale_earlier", "earlier\nerroneous"), ("delayed_report", "delayed\nreport"), ("low_trust_error", "latest err.\n(low trust)"), ("other_error", "latest err.\n(other)"), ("retraction", "latest\nwithdrawn"), ("poisoning", "latest is\ninjection")]
    fig, ax = plt.subplots(figsize=(7.2, 2.1))
    w = 0.2; xs = range(len(regs))
    for i, (name, lab, col) in enumerate((("always_commit", "last write wins", C["temporal_db"]), ("palimpsest", "Palimpsest P0c (world)", C["palimpsest"]), ("palimpsest_argmax", "Palimpsest + support argmax", "#7fa6cc"))):
        vals = [(p if reg == "poisoning" else d)[reg][name]["world_acc"] for reg, _ in regs]
        ax.bar([x + (i - 1) * w for x in xs], vals, w, color=col, label=lab)
    abst = [(p if reg == "poisoning" else d)[reg]["palimpsest"]["abstain"] for reg, _ in regs]
    ax.plot([x for x in xs], abst, "k_", ms=10, mew=1.2, label="P0c abstention rate")
    ax.set_xticks(list(xs)); ax.set_xticklabels([l for _, l in regs], fontsize=6.5); ax.set_ylabel("accuracy vs hidden world"); ax.set_ylim(0, 1.08); ax.legend(fontsize=6, ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.28))
    ns = [(p if reg == "poisoning" else d)[reg]["n"] for reg, _ in regs]
    for x, n in zip(xs, ns):
        ax.text(x, 1.02, f"n={n}", ha="center", fontsize=5.5, color="#444444")
    fig.savefig(os.path.join(FIG, "regime.pdf")); plt.close(fig)


def fig_reliability():
    p = os.path.join(ROOT, "data", "holm_tests.json")
    if not os.path.exists(p):
        return
    r = json.load(open(p))["reliability"]
    fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.3))
    for ax, (k, title) in zip(axes, (("support", "evidence-model support"), ("verbalised", "verbalised confidence"), ("sampling", "sample agreement (k=5)"))):
        b = r[k]
        ax.plot([0, 1], [0, 1], "--", color="#999999", lw=0.8)
        ax.plot([x["conf"] for x in b], [x["acc"] for x in b], "o-", color=C["palimpsest"], ms=3, lw=1.1)
        for x in b:
            ax.annotate(str(x["n"]), (x["conf"], x["acc"]), fontsize=4.5, textcoords="offset points", xytext=(0, 4), ha="center", color="#555555")
        ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.set_xlabel("predicted probability"); ax.set_title(title, fontsize=8)
    axes[0].set_ylabel("observed frequency (world)")
    fig.savefig(os.path.join(FIG, "reliability.pdf")); plt.close(fig)


if __name__ == "__main__":
    fig_systems(); fig_noise(); fig_regime(); fig_reliability()
    print("figures written to", FIG, os.listdir(FIG))
