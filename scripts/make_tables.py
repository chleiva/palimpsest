"""Emit LaTeX tables and figures from result files (never hand-typed numbers).
Usage: python scripts/make_tables.py  -> paper/tables/*.tex, paper/figures/*.pdf
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAB = os.path.join(ROOT, "paper", "tables"); FIG = os.path.join(ROOT, "paper", "figures")
os.makedirs(TAB, exist_ok=True); os.makedirs(FIG, exist_ok=True)

NAMES = {"palimpsest": "\\textsc{Palimpsest}", "palimpsest_noprop": "\\quad no propagation", "palimpsest_commit": "\\quad forced commit",
         "log_query_time": "Log + rule adjudicator", "log_rule_adjudicator": "Symbolic replay (rule adjudicator)", "log_llm_adjudicator": "Claims log + LLM adjudicator",
         "log_llm_topk40": "\\quad top-40 entries (original, 30 str.)", "log_nl_adjudicator": "Raw-report log + LLM adjudicator (30 str.)",
         "temporal_db": "Temporal DB", "always_abstain": "Always abstain", "always_commit": "Always commit",
         "log_llm_adjudicator_c2": "Claims log + LLM adj.\\ (amended contract, 30 str.)", "log_llm_topk10_c2": "\\quad top-10 entries", "log_llm_topk20_c2": "\\quad top-20 entries",
         "log_llm_topk40_c2": "\\quad top-40 entries", "log_nl_adjudicator_c2": "Raw-report log + LLM adj.\\ (amended, 30 str.)"}
ORDER = ["palimpsest", "palimpsest_noprop", "palimpsest_commit", "log_rule_adjudicator", "log_query_time", "log_llm_adjudicator", "log_llm_topk40", "log_nl_adjudicator",
         "log_llm_adjudicator_c2", "log_llm_topk10_c2", "log_llm_topk20_c2", "log_llm_topk40_c2", "log_nl_adjudicator_c2", "temporal_db", "always_abstain", "always_commit"]


def fmt(t):
    if t is None or not isinstance(t, (list, tuple)):
        return "--"
    m, lo, hi = t
    if m != m:
        return "--"
    return f"{m:.3f} {{\\tiny[{lo:.2f},{hi:.2f}]}}"


def table_systems(path, out, caption, label, cols=("warranted_acc", "warranted_direct_acc", "resolvable_acc", "unresolved_acc", "commit_rate", "unsupported_prop", "prov_precision", "prov_recall")):
    r = json.load(open(path))["summary"]
    heads = {"cost_tokens": "Cost (tok/stream)", "warranted_acc": "Warr.\\ downstream", "warranted_direct_acc": "Warr.\\ direct", "resolvable_acc": "Resolvable", "unresolved_acc": "Unresolved",
             "commit_rate": "Commit rate$\\downarrow$", "unsupported_prop": "Unsupp.\\ prop.$\\downarrow$", "prov_precision": "Prov.\\ P", "prov_recall": "Prov.\\ R",
             "malformed_rate": "Malformed$\\downarrow$"}
    lines = ["\\begin{sidewaystable}\\centering\\footnotesize\\setlength{\\tabcolsep}{3.5pt}", f"\\caption{{{caption}}}\\label{{{label}}}",
             "\\begin{tabular}{l" + "c" * len(cols) + "}", "\\toprule", "System & " + " & ".join(heads[c] for c in cols) + " \\\\", "\\midrule"]
    for name in ORDER:
        if name not in r:
            continue
        cells = []
        for c in cols:
            v = r[name].get(c)
            cells.append(f"{v[0]/1000:.0f}k" if c == "cost_tokens" and isinstance(v, (list, tuple)) else fmt(v))
        lines.append(NAMES[name] + " & " + " & ".join(cells) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", "\\end{sidewaystable}"]
    open(os.path.join(TAB, out), "w").write("\n".join(lines))


def table_longmemeval(path, out):
    r = json.load(open(path))
    names = {"palimpsest": "\\pal{} (P0c)", "palimpsest_selfupdate": "\\pal{} + self-update (exploratory)", "temporal_db": "Temporal DB (last write wins)",
             "always_commit": "Always-commit", "always_abstain": "Always-abstain", "log_llm_adjudicator": "Claims log + LLM adjudicator"}
    lines = ["\\begin{table}[t]\\centering\\footnotesize",
             f"\\caption{{LongMemEval knowledge-update items ({r['_n_items']}; {r['_n_mapped']} mapped to an extracted attribute). Systems answer one structured slot from claims extracted turn by turn; a Haiku judge compares the answer with the reference. Coverage = share answered as established; accuracy over all items and over answered items. Not comparable to published LongMemEval scores.}}\\label{{tab:lme}}",
             "\\begin{tabular}{lccc}", "\\toprule", "System & Coverage & Acc.\\ (all) & Acc.\\ (answered) \\\\", "\\midrule"]
    for k in ("palimpsest", "palimpsest_selfupdate", "temporal_db", "always_commit", "always_abstain", "log_llm_adjudicator"):
        if k in r:
            lines.append(f"{names[k]} & {r[k]['coverage']:.2f} & {r[k]['accuracy_overall']:.3f} & {r[k]['accuracy_when_answered']:.3f} \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
    open(os.path.join(TAB, out), "w").write("\n".join(lines))


def table_regime(paths, out):
    """Regime table: paired P0c vs P0cSU on the same fresh streams; poisoning row from the attack streams (P0c only)."""
    names = {"self_update": "self-update (same origin, latest true)", "multi_source_update": "multi-source update (latest true)", "stale_earlier": "earlier report erroneous, latest true",
             "delayed_report": "delayed report (latest true but older)", "low_trust_error": "latest erroneous, low-trust source", "other_error": "latest erroneous, other source",
             "retraction": "latest report withdrawn", "poisoning": "latest report is an injection$^\\dagger$", "no_conflict": "no conflict"}
    lines = ["\\begin{sidewaystable}\\centering\\small", "\\caption{When is recency right? Value queries on single-valued keys of 200 fresh generated streams (seeds 20000--20199), classified from the hidden generator labels by what the latest report on the key is; the same queries are scored under P0c and under the self-update variant P0cSU (paired). Accuracy against the hidden world value; LWW = last-write-wins by report time; valid = by valid-time anchor (temporal DB); abst.\\ = abstention rate; wrong commit = committed to a value other than the world's (not a transition); argmax = support-ranked commitment on unresolved slots (P0c). $^\\dagger$Poisoning row from 60 attack streams (rate 0.2, low channel), P0c only; its last column is the share of queries committed to the injected value (LWW: 1.00). Setting 1 (500 streams) gives the same picture (Appendix~\\ref{app:tables}).}\\label{tab:regime}",
             "\\begin{tabular}{lrcccccccccc}", "\\toprule", "Regime (latest report) & $n$ & LWW & valid & P0c world & P0c abst. & P0c wrong commit & P0cSU world & P0cSU abst. & P0cSU wrong commit & argmax & injected \\\\", "\\midrule"]
    fa = json.load(open(paths["fresh_p0c"])); fb = json.load(open(paths["fresh_su"])); pois = json.load(open(paths["poison"]))
    for reg in ("self_update", "multi_source_update", "stale_earlier", "delayed_report", "low_trust_error", "other_error", "retraction", "no_conflict", "poisoning"):
        src = pois if reg == "poisoning" else fa
        if reg not in src:
            continue
        c = src[reg]; su = fb.get(reg, {}).get("palimpsest") if reg != "poisoning" else None
        row = f"{names[reg]} & {c['n']} & {c['always_commit']['world_acc']:.2f} & {c['temporal_db']['world_acc']:.2f} & {c['palimpsest']['world_acc']:.2f} & {c['palimpsest']['abstain']:.2f} & {c['palimpsest']['wrong_commit']:.2f} & "
        row += (f"{su['world_acc']:.2f} & {su['abstain']:.2f} & {su['wrong_commit']:.2f}" if su else "-- & -- & --")
        row += f" & {c['palimpsest_argmax']['world_acc']:.2f} & " + (f"{c['palimpsest']['latest_commit']:.2f}" if reg == "poisoning" else "--") + " \\\\"
        lines.append(row)
    lines += ["\\bottomrule", "\\end{tabular}", "\\end{sidewaystable}"]
    open(os.path.join(TAB, out), "w").write("\n".join(lines))


def table_regime_s1(path, out):
    names = {"self_update": "self-update", "multi_source_update": "multi-source update", "stale_earlier": "earlier report erroneous", "delayed_report": "delayed report",
             "low_trust_error": "latest erroneous, low-trust", "other_error": "latest erroneous, other", "retraction": "latest withdrawn", "no_conflict": "no conflict"}
    d = json.load(open(path))
    lines = ["\\begin{table}[t]\\centering\\small", "\\caption{Regime table on the 500 frozen Setting 1 streams (P0c; same definitions as Table~\\ref{tab:regime}).}\\label{tab:regime-s1}",
             "\\begin{tabular}{lrccccc}", "\\toprule", "Regime & $n$ & LWW & valid & P0c world & P0c abst. & P0c wrong commit \\\\", "\\midrule"]
    for reg, nm in names.items():
        if reg in d:
            c = d[reg]; lines.append(f"{nm} & {c['n']} & {c['always_commit']['world_acc']:.2f} & {c['temporal_db']['world_acc']:.2f} & {c['palimpsest']['world_acc']:.2f} & {c['palimpsest']['abstain']:.2f} & {c['palimpsest']['wrong_commit']:.2f} \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
    open(os.path.join(TAB, out), "w").write("\n".join(lines))


def table_systems_bench(path, out):
    d = json.load(open(path))["summary"]
    lines = ["\\begin{sidewaystable}\\centering\\small", "\\caption{Incremental justification maintenance vs symbolic replay of the same semantics on the same streams and queries (no LLM). CPU seconds per stream (process time), query latency mean / p95 / max in ms, peak traced memory in MB; $r$ = queries per observation. Answers agree on every query (last column: disagreements / answers). Scale rows: generated streams with $m$ reports per key and horizon $T$ days, $r=1$.}\\label{tab:sys}",
             "\\begin{tabular}{llrrrrrrrr}", "\\toprule", "Workload & System & CPU total & CPU write & lat.\\ mean & p95 & max & mem & recomputes & disagree \\\\", "\\midrule"]
    order = [k for k in d if k.startswith("setting1")] + sorted(k for k in d if k.startswith("scale"))
    for k in order:
        c = d[k]
        wl = k.replace("setting1|", "Setting 1, ").replace("scale_m", "scale $m$=").replace("_T", ", $T$=").replace("|r=", ", $r$=")
        for i, name in enumerate(("incremental", "replay_cold", "replay_lazy")):
            x = c[name]
            lines.append((wl if i == 0 else "") + f" & {name.replace('_', ' ')} & {x['cpu_total_s']:.2f} & {x['cpu_write_s']:.2f} & {x['lat_mean_ms']:.1f} & {x['lat_p95_ms']:.1f} & {x['lat_max_ms']:.0f} & {x['peak_mem_mb']:.1f} & {x['key_recomputes']:.0f} & "
                         + (f"{c['disagreements_inc_vs_cold']}/{c['n_answers']}" if i == 0 else "") + " \\\\")
        lines.append("\\addlinespace[2pt]")
    lines += ["\\bottomrule", "\\end{tabular}", "\\end{sidewaystable}"]
    open(os.path.join(TAB, out), "w").write("\n".join(lines))


def table_transitions(path, out, caption, label):
    d = json.load(open(path))["transitions"]
    lines = ["\\begin{table}[t]\\centering\\small", f"\\caption{{{caption}}}\\label{{{label}}}", "\\begin{tabular}{lrcccc c}", "\\toprule",
             "System & $n$ & C$\\to$C & C$\\to$W & W$\\to$C & W$\\to$W & instability \\\\", "\\midrule"]
    for name in ORDER:
        if name not in d:
            continue
        c = d[name]; n = c["n"]
        lines.append(f"{NAMES.get(name, name)} & {n} & " + " & ".join(f"{c.get(k, 0)/n:.3f}" for k in ("C->C", "C->W", "W->C", "W->W")) + f" & {c['instability']/n:.3f} \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
    open(os.path.join(TAB, out), "w").write("\n".join(lines))


def table_slots(path, out):
    r = json.load(open(path))["summary"]
    slots = list(r["palimpsest"]["slot_acc"].keys())
    names = {"asof": "as-of valid time", "belief_asof": "as-of belief time", "current": "current", "downstream": "downstream (derived)",
             "reported": "reported", "yesno_changed": "changed?", "yesno_erroneous": "erroneous?", "yesno_holds": "holds at $t$?"}
    sysn = ["palimpsest", "palimpsest_noprop", "palimpsest_commit", "temporal_db", "always_commit", "always_abstain"]
    lines = ["\\begin{table}[t]\\centering\\small", "\\caption{Setting 1: exact accuracy by query slot (mean over 500 streams).}\\label{tab:slots}",
             "\\begin{tabular}{l" + "c" * len(sysn) + "}", "\\toprule", "Slot & " + " & ".join(NAMES[x].replace("\\quad ", "") for x in sysn) + " \\\\", "\\midrule"]
    for sl in slots:
        lines.append(names.get(sl, sl) + " & " + " & ".join(f"{r[x]['slot_acc'].get(sl, float('nan')):.3f}" for x in sysn) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
    open(os.path.join(TAB, out), "w").write("\n".join(lines))


def table_noise(path, out):
    rows = json.load(open(path))
    lines = ["\\begin{table}[t]\\centering\\small",
             "\\caption{RQ2 corruption curve (50 Setting 2 streams, mock extractor with injected error rates). Warranted downstream accuracy; PALIMPSEST resolvable and unresolved accuracy.}\\label{tab:noise}",
             "\\begin{tabular}{llcccccc}", "\\toprule",
             "Error type & rate & \\textsc{Palimpsest} & no prop. & Temporal DB & Always commit & PAL resolvable & PAL unresolved \\\\", "\\midrule"]
    names = {"slot_error": "wrong value", "missed_cue": "change cue dropped", "spurious_cue": "change cue added", "missed_valid": "date dropped"}
    for r in rows:
        lines.append(f"{names[r['kind']]} & {r['rate']:.2f} & {r['palimpsest']['warranted_acc']:.3f} & {r['palimpsest_noprop']['warranted_acc']:.3f} & {r['temporal_db']['warranted_acc']:.3f} & {r['always_commit']['warranted_acc']:.3f} & {r['palimpsest']['resolvable_acc']:.3f} & {r['palimpsest']['unresolved_acc']:.3f} \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
    open(os.path.join(TAB, out), "w").write("\n".join(lines))


def table_rq3(path, out):
    r = json.load(open(path))
    names = {"support_default": "Evidence model, declared priors", "support_learned": "Evidence model, learned class priors",
             "class_prior_only": "Class prior only", "logreg_features": "Logistic regression on evidence features", "always_half": "Constant 0.5",
             "ablation_no_origin_grouping": "\\quad without origin grouping", "ablation_no_recency": "\\quad without recency", "ablation_no_cues": "\\quad without cue adjustments"}
    lines = ["\\begin{table}[t]\\centering\\small", "\\caption{RQ3, Setting 1 (held-out streams): claim-level calibration of support against the hidden world. Lower is better.}\\label{tab:rq3}",
             "\\begin{tabular}{lccc}", "\\toprule", "Confidence & Brier & ECE & AURC \\\\", "\\midrule"]
    for k in ("support_default", "support_learned", "ablation_no_origin_grouping", "ablation_no_recency", "ablation_no_cues", "class_prior_only", "logreg_features", "always_half"):
        if k in r:
            v = r[k]
            lines.append(f"{names[k]} & {v['brier']:.3f} & {v['ece']:.3f} & {v['aurc']:.3f} \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
    open(os.path.join(TAB, out), "w").write("\n".join(lines))


def table_poison(path, out):
    r = json.load(open(path))
    lines = ["\\begin{table}[t]\\centering\\small",
             "\\caption{Poisoning (Setting 1, 60 streams per cell). Attacker injects false assertions at a rate of the honest ones, half with a false change cue; harm = share of value queries answered \\emph{established} with the poisoned value; support = mean support the evidence model assigns to poisoned vs.\\ honest candidates.}\\label{tab:poison}",
             "\\begin{tabular}{llcccccc}", "\\toprule",
             "Channel & Rate & \\multicolumn{2}{c}{\\textsc{Palimpsest}} & \\multicolumn{2}{c}{Temporal DB} & \\multicolumn{2}{c}{Support} \\\\",
             " & & harm$\\downarrow$ & unresolved & harm$\\downarrow$ & unresolved & poisoned & honest \\\\", "\\midrule"]
    for k, v in r.items():
        ch, rate = k.split("@")
        p, t = v["palimpsest"], v["temporal_db"]
        lines.append(f"{ch} & {float(rate):.2f} & {p['harm_rate']:.3f} & {p['unresolved_share']:.2f} & {t['harm_rate']:.3f} & {t['unresolved_share']:.2f} & {v['support_poisoned_mean']:.2f} & {v['support_honest_mean']:.2f} \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
    open(os.path.join(TAB, out), "w").write("\n".join(lines))


def table_sensitivity(paths, out):
    rows = []
    for pol, path in paths.items():
        if not os.path.exists(path):
            continue
        r = json.load(open(path))["summary"]
        rows.append((pol, r))
    lines = ["\\begin{table}[t]\\centering\\small",
             "\\caption{Sensitivity of the Setting 1 gate to the dispute semantics (500 streams). Warranted downstream queries per stream, and the propagation on$-$off difference on them.}\\label{tab:sens}",
             "\\begin{tabular}{lcccc}", "\\toprule", "Policy & warr./stream & \\textsc{Palimpsest} & no propagation & Temporal DB \\\\", "\\midrule"]
    for pol, r in rows:
        lines.append(f"{pol} & {r['palimpsest']['n_warranted_per_stream']:.2f} & {fmt(r['palimpsest']['warranted_acc'])} & {fmt(r['palimpsest_noprop']['warranted_acc'])} & {fmt(r['temporal_db']['warranted_acc'])} \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
    open(os.path.join(TAB, out), "w").write("\n".join(lines))


def numbers(d):
    """Macros for numbers quoted in the prose (paper/tables/numbers.tex)."""
    from eval.metrics import bootstrap_paired, bootstrap_mean
    m = {}
    def macro(name, val):
        m[name] = val
    p = os.path.join(d, "setting1_results.json")
    if os.path.exists(p):
        r = json.load(open(p)); ps = r["per_stream"]; sm = r["summary"]
        (dd, lo, hi), n = bootstrap_paired([x["warranted_acc"] for x in ps["palimpsest"]], [x["warranted_acc"] for x in ps["palimpsest_noprop"]], n_boot=5000)
        macro("sOnePropEffect", f"{100*dd:.1f}"); macro("sOnePropLo", f"{100*lo:.1f}"); macro("sOnePropHi", f"{100*hi:.1f}"); macro("sOnePropN", str(n))
        (dd, lo, hi), n = bootstrap_paired([x["unsupported_prop"] for x in ps["palimpsest_commit"]], [x["unsupported_prop"] for x in ps["palimpsest"]], n_boot=5000)
        macro("sOneCommitUnsup", f"{100*dd:.1f}"); macro("sOneCommitUnsupLo", f"{100*lo:.1f}"); macro("sOneCommitUnsupHi", f"{100*hi:.1f}")
        macro("sOneCommitRate", f"{100*sm['palimpsest_commit']['commit_rate'][0]:.0f}")
        macro("sOneAbstainRes", f"{sm['always_abstain']['resolvable_acc'][0]:.3f}"); macro("sOneAbstainUnres", f"{sm['always_abstain']['unresolved_acc'][0]:.3f}")
        macro("sOneCommitRes", f"{sm['always_commit']['resolvable_acc'][0]:.3f}"); macro("sOneCommitUnres", f"{sm['always_commit']['unresolved_acc'][0]:.3f}")
        macro("sOneTdbWarr", f"{100*(1-sm['temporal_db']['warranted_acc'][0]):.1f}"); macro("sOneTdbCommit", f"{100*sm['temporal_db']['commit_rate'][0]:.0f}")
        macro("sOneProvP", f"{sm['palimpsest']['prov_precision'][0]:.2f}"); macro("sOneProvR", f"{sm['palimpsest']['prov_recall'][0]:.2f}")
        macro("sOneWarrPerStream", f"{sm['palimpsest']['n_warranted_per_stream']:.1f}")
        macro("sOneAnswers", f"{sum(x['n_resolvable']+x['n_unresolved'] for x in ps['palimpsest'])}")
    for pol, key in (("P0", "sOneLitPZero"), ("P1", "sOnePOne")):
        p = os.path.join(d, f"setting1_{pol}_results.json")
        if os.path.exists(p):
            r = json.load(open(p)); ps = r["per_stream"]; sm = r["summary"]
            (dd, lo, hi), n = bootstrap_paired([x["warranted_acc"] for x in ps["palimpsest"]], [x["warranted_acc"] for x in ps["palimpsest_noprop"]], n_boot=5000)
            macro(key + "Effect", f"{100*dd:.1f}"); macro(key + "Warr", f"{sm['palimpsest']['n_warranted_per_stream']:.1f}")
    p = os.path.join(d, "rq3_setting1.json")
    if os.path.exists(p):
        r = json.load(open(p))
        for k, nm in (("support_learned", "RqLearned"), ("class_prior_only", "RqPrior"), ("logreg_features", "RqLogreg"), ("support_default", "RqDefault"), ("ablation_no_recency", "RqNoRec"), ("ablation_no_origin_grouping", "RqNoOrig")):
            if k in r:
                macro(nm + "Ece", f"{r[k]['ece']:.3f}"); macro(nm + "Brier", f"{r[k]['brier']:.3f}"); macro(nm + "Aurc", f"{r[k]['aurc']:.3f}")
        macro("RqN", str(r["support_learned"]["n"]))
    p = os.path.join(d, "poison_setting1.json")
    if os.path.exists(p):
        r = json.load(open(p))
        v = r["low@0.2"]
        macro("PoisHarmPal", f"{100*v['palimpsest']['harm_rate']:.1f}"); macro("PoisHarmTdb", f"{100*v['temporal_db']['harm_rate']:.1f}"); macro("PoisHarmCommit", f"{100*v['always_commit']['harm_rate']:.1f}")
        macro("PoisSupLowPois", f"{min(r[k]['support_poisoned_mean'] for k in r if k.startswith('low')):.2f}--{max(r[k]['support_poisoned_mean'] for k in r if k.startswith('low')):.2f}")
        macro("PoisSupLowHon", f"{min(r[k]['support_honest_mean'] for k in r if k.startswith('low')):.2f}--{max(r[k]['support_honest_mean'] for k in r if k.startswith('low')):.2f}")
        macro("PoisSupTrPois", f"{min(r[k]['support_poisoned_mean'] for k in r if k.startswith('trusted')):.2f}--{max(r[k]['support_poisoned_mean'] for k in r if k.startswith('trusted')):.2f}")
        macro("PoisSupTrHon", f"{min(r[k]['support_honest_mean'] for k in r if k.startswith('trusted')):.2f}--{max(r[k]['support_honest_mean'] for k in r if k.startswith('trusted')):.2f}")
    p = os.path.join(d, "s2", "_results.json")
    if os.path.exists(p):
        r = json.load(open(p)); ps = r["per_stream"]; sm = r["summary"]
        (dd, lo, hi), n = bootstrap_paired([x["warranted_acc"] for x in ps["palimpsest"]], [x["warranted_acc"] for x in ps["log_llm_adjudicator"]], n_boot=5000)
        macro("sTwoHOne", f"{100*dd:.1f}"); macro("sTwoHOneLo", f"{100*lo:.1f}"); macro("sTwoHOneHi", f"{100*hi:.1f}"); macro("sTwoHOneN", str(n))
        (dd, lo, hi), n = bootstrap_paired([x["warranted_acc"] for x in ps["palimpsest"]], [x["warranted_acc"] for x in ps["palimpsest_noprop"]], n_boot=5000)
        macro("sTwoProp", f"{100*dd:.1f}"); macro("sTwoPropLo", f"{100*lo:.1f}"); macro("sTwoPropHi", f"{100*hi:.1f}")
        for key, nm in (("palimpsest", "Pal"), ("log_llm_adjudicator", "Log"), ("log_nl_adjudicator", "Nl"), ("temporal_db", "Tdb"), ("palimpsest_commit", "Commit"), ("log_llm_topk40", "Topk"), ("palimpsest_noprop", "Noprop"), ("log_rule_adjudicator", "Rule")):
            if key in sm:
                for c, cn in (("warranted_acc", "Warr"), ("resolvable_acc", "Res"), ("unresolved_acc", "Unres"), ("commit_rate", "Commit"), ("unsupported_prop", "Unsup")):
                    macro(f"sTwo{nm}{cn}", f"{sm[key][c][0]:.3f}")
                macro(f"sTwo{nm}Cost", f"{sm[key]['cost_usd'][0]:.3f}"); macro(f"sTwo{nm}Tok", f"{sm[key]['cost_tokens'][0]/1000:.0f}")
        ex = r["summary"]["_extraction"]
        macro("sTwoExtSlot", f"{100*ex['slot_error_rate']:.1f}"); macro("sTwoExtMissed", f"{100*ex['missed_ambiguity_rate']:.1f}"); macro("sTwoExtSpur", f"{100*ex['spurious_ambiguity_rate']:.1f}"); macro("sTwoExtValid", f"{100*ex['valid_cue_error_rate']:.1f}"); macro("sTwoExtFail", f"{100*ex['failure_rate']:.1f}")
        macro("sTwoWarrPerStream", f"{sm['palimpsest']['n_warranted_per_stream']:.2f}")
    p = os.path.join(d, "s2", "_results.json")
    if os.path.exists(p):
        r = json.load(open(p)); ps = r["per_stream"]; sm = r["summary"]
        if "log_llm_adjudicator_c2" in ps:
            n2 = len(ps["log_llm_adjudicator_c2"])
            pal_sub = ps["palimpsest"][:n2]
            (mm, lo, hi) = bootstrap_mean([x["warranted_acc"] for x in pal_sub if x["warranted_acc"] is not None], n_boot=5000)
            macro("sTwoSubPalWarr", f"{mm:.3f}"); macro("sTwoSubN", str(n2))
            for key, nm in (("log_llm_adjudicator_c2", "CtwoLog"), ("log_llm_topk10_c2", "CtwoTopTen"), ("log_llm_topk20_c2", "CtwoTopTwenty"), ("log_llm_topk40_c2", "CtwoTopForty"), ("log_nl_adjudicator_c2", "CtwoNl"),
                            ("log_llm_topk40", "SubTopForty"), ("log_nl_adjudicator", "SubNl")):
                if key not in ps:
                    continue
                for c, cn in (("warranted_acc", "Warr"), ("warranted_direct_acc", "Direct"), ("resolvable_acc", "Res"), ("unresolved_acc", "Unres"), ("commit_rate", "Commit"), ("malformed_rate", "Malformed")):
                    macro(f"sTwo{nm}{cn}", f"{sm[key][c][0]:.3f}")
                macro(f"sTwo{nm}Tok", f"{sm[key]['cost_tokens'][0]/1000:.0f}"); macro(f"sTwo{nm}Cost", f"{sm[key]['cost_usd'][0]:.3f}")
                (dd, lo, hi), n = bootstrap_paired([x["warranted_acc"] for x in pal_sub], [x["warranted_acc"] for x in ps[key]], n_boot=5000)
                macro(f"sTwo{nm}Diff", f"{100*dd:.1f}"); macro(f"sTwo{nm}DiffLo", f"{100*lo:.1f}"); macro(f"sTwo{nm}DiffHi", f"{100*hi:.1f}"); macro(f"sTwo{nm}DiffN", str(n))
            # original-protocol adjudicator on the same subset, paired
            (dd, lo, hi), n = bootstrap_paired([x["warranted_acc"] for x in pal_sub], [x["warranted_acc"] for x in ps["log_llm_adjudicator"][:n2]], n_boot=5000)
            macro("sTwoSubLogDiff", f"{100*dd:.1f}"); macro("sTwoSubLogDiffLo", f"{100*lo:.1f}"); macro("sTwoSubLogDiffHi", f"{100*hi:.1f}")
            (mm, lo, hi) = bootstrap_mean([x["warranted_acc"] for x in ps["log_llm_adjudicator"][:n2] if x["warranted_acc"] is not None], n_boot=5000); macro("sTwoSubLogWarr", f"{mm:.3f}")
    p = os.path.join(d, "s3", "_results.json")
    if os.path.exists(p):
        r = json.load(open(p)); sm = r["summary"]
        for key, nm in (("log_llm_adjudicator_c2", "CtwoLog"), ("log_nl_adjudicator_c2", "CtwoNl")):
            if key in sm:
                for c, cn in (("warranted_acc", "Warr"), ("warranted_direct_acc", "Direct"), ("resolvable_acc", "Res"), ("unresolved_acc", "Unres"), ("commit_rate", "Commit")):
                    macro(f"sThree{nm}{cn}", f"{sm[key][c][0]:.3f}")
    p = os.path.join(d, "s2_strong", "_results.json")
    if os.path.exists(p):
        r = json.load(open(p)); ps = r["per_stream"]; sm = r["summary"]
        (dd, lo, hi), n = bootstrap_paired([x["warranted_acc"] for x in ps["palimpsest"]], [x["warranted_acc"] for x in ps["log_llm_adjudicator"]], n_boot=5000)
        macro("sStrongHOne", f"{100*dd:.1f}"); macro("sStrongHOneLo", f"{100*lo:.1f}"); macro("sStrongHOneHi", f"{100*hi:.1f}")
        macro("sStrongPalWarr", f"{sm['palimpsest']['warranted_acc'][0]:.3f}"); macro("sStrongLogWarr", f"{sm['log_llm_adjudicator']['warranted_acc'][0]:.3f}"); macro("sStrongLogCommit", f"{sm['log_llm_adjudicator']['commit_rate'][0]:.3f}")
        macro("sStrongExtSlot", f"{100*sm['_extraction']['slot_error_rate']:.1f}")
    p = os.path.join(d, "s2", "_crossover.json")
    if os.path.exists(p):
        r = json.load(open(p))
        macro("xE", f"{r['E_extraction_tokens_per_stream']/1000:.0f}"); macro("xAnl", f"{r['A_nl_tokens_per_query']/1000:.1f}"); macro("xAlog", f"{r['A_log_tokens_per_query']/1000:.1f}"); macro("xRstar", f"{r['r_star_nl']:.2f}"); macro("xNobs", f"{r['n_obs']:.0f}")
    p = os.path.join(d, "s2", "_rq3.json")
    if os.path.exists(p):
        r = json.load(open(p))
        for k, nm in (("support_on_extracted", "RqTwoSup"), ("verbalised", "RqTwoVerb"), ("sampling_k5", "RqTwoSamp")):
            macro(nm + "Ece", f"{r[k]['ece']:.3f}"); macro(nm + "Brier", f"{r[k]['brier']:.3f}"); macro(nm + "Aurc", f"{r[k]['aurc']:.3f}"); macro(nm + "N", str(r[k]["n"]))
    p = os.path.join(d, "noise_grid", "_noise_grid.json")
    if os.path.exists(p):
        r = {(x["kind"], x["rate"]): x for x in json.load(open(p))}
        macro("nzSlotTwentyPal", f"{r[('slot_error',0.2)]['palimpsest']['warranted_acc']:.3f}"); macro("nzSlotTwentyTdb", f"{r[('slot_error',0.2)]['temporal_db']['warranted_acc']:.3f}")
        macro("nzSlotThirtyfivePal", f"{r[('slot_error',0.35)]['palimpsest']['warranted_acc']:.3f}"); macro("nzSlotThirtyfiveTdb", f"{r[('slot_error',0.35)]['temporal_db']['warranted_acc']:.3f}")
        macro("nzCueFiftyPal", f"{r[('missed_cue',0.5)]['palimpsest']['warranted_acc']:.3f}"); macro("nzCueFiftyTdb", f"{r[('missed_cue',0.5)]['temporal_db']['warranted_acc']:.3f}")
    p = os.path.join(d, "s3", "_results.json")
    if os.path.exists(p):
        r = json.load(open(p)); ps = r["per_stream"]; sm = r["summary"]
        (dd, lo, hi), n = bootstrap_paired([x["warranted_acc"] for x in ps["palimpsest"]], [x["warranted_acc"] for x in ps["log_llm_adjudicator"]], n_boot=5000)
        macro("sThreeHOne", f"{100*dd:.1f}"); macro("sThreeHOneLo", f"{100*lo:.1f}"); macro("sThreeHOneHi", f"{100*hi:.1f}"); macro("sThreeHOneN", str(n))
        (dd, lo, hi), n = bootstrap_paired([x["warranted_acc"] for x in ps["palimpsest"]], [x["warranted_acc"] for x in ps["palimpsest_noprop"]], n_boot=5000)
        macro("sThreeProp", f"{100*dd:.1f}"); macro("sThreePropLo", f"{100*lo:.1f}"); macro("sThreePropHi", f"{100*hi:.1f}")
        (dd, lo, hi), n = bootstrap_paired([x["warranted_direct_acc"] for x in ps["palimpsest"]], [x["warranted_direct_acc"] for x in ps["log_llm_adjudicator"]], n_boot=5000)
        macro("sThreeDirect", f"{100*dd:.1f}"); macro("sThreeDirectLo", f"{100*lo:.1f}"); macro("sThreeDirectHi", f"{100*hi:.1f}"); macro("sThreeDirectN", str(n))
        for key, nm in (("palimpsest", "Pal"), ("log_llm_adjudicator", "Log"), ("temporal_db", "Tdb"), ("log_rule_adjudicator", "Rule"), ("palimpsest_commit", "Commit"), ("log_nl_adjudicator", "Nl")):
            if key in sm:
                for c, cn in (("warranted_acc", "Warr"), ("warranted_direct_acc", "Direct"), ("resolvable_acc", "Res"), ("unresolved_acc", "Unres"), ("commit_rate", "Commit"), ("unsupported_prop", "Unsup")):
                    if isinstance(sm[key].get(c), (list, tuple)) and sm[key][c][0] == sm[key][c][0]:
                        macro(f"sThree{nm}{cn}", f"{sm[key][c][0]:.3f}")
        ex = r["summary"]["_extraction"]
        macro("sThreeExtSlot", f"{100*ex['slot_error_rate']:.1f}"); macro("sThreeExtMissed", f"{100*ex['missed_ambiguity_rate']:.1f}"); macro("sThreeExtSpur", f"{100*ex['spurious_ambiguity_rate']:.1f}"); macro("sThreeExtFail", f"{100*ex['failure_rate']:.1f}")
        macro("sThreeWarrPerStream", f"{sm['palimpsest']['n_warranted_per_stream']:.2f}")
        cb = os.path.join(d, "s3", "_convention_breakdown.json")
        if os.path.exists(cb):
            c = json.load(open(cb))["setting3"]
            macro("sThreeEstTotal", str(c["est_total"])); macro("sThreeEstEmpty", str(c["est_empty"])); macro("sThreeHoldsFalse", str(c["holds_false"])); macro("sThreeWarrEmpty", str(c["warr_empty"])); macro("sThreeWarrTotal", str(c["warr_total"]))
            for key, nm in (("palimpsest", "Pal"), ("log_llm_adjudicator", "Log"), ("temporal_db", "Tdb")):
                macro(f"sThree{nm}ResNe", f"{c[key]['res_ne'][0]:.3f}"); macro(f"sThree{nm}WarrNe", f"{c[key]['warr_ne'][0]:.3f}")
    p = os.path.join(d, "longmemeval", "results.json")
    if os.path.exists(p):
        r = json.load(open(p))
        for key, nm in (("palimpsest", "Pal"), ("palimpsest_selfupdate", "PalSu"), ("temporal_db", "Tdb"), ("log_llm_adjudicator", "Log"), ("always_commit", "Commit")):
            if key in r:
                macro(f"lme{nm}Cov", f"{r[key]['coverage']:.2f}"); macro(f"lme{nm}Acc", f"{r[key]['accuracy_overall']:.3f}"); macro(f"lme{nm}AccAns", f"{r[key]['accuracy_when_answered']:.3f}")
        macro("lmeN", str(r["_n_items"])); macro("lmeMapped", str(r["_n_mapped"]))
        b = os.path.join(d, "longmemeval", "breakdown_v2.json")
        if os.path.exists(b):
            bb = json.load(open(b))["status_counts"]
            macro("lmePalUnres", str(bb.get("pal_unresolved", 0))); macro("lmePalEst", str(bb.get("pal_established", 0)))
    p = os.path.join(d, "systems_bench.json")
    if os.path.exists(p):
        sb = json.load(open(p))["summary"]
        for key, nm in (("setting1|r=0.1", "RpOne"), ("setting1|r=0.33", "RpThird"), ("setting1|r=1.0", "ROne"), ("setting1|r=3.0", "RThree"), ("scale_m13_T60|r=1.0", "MThirteen"), ("scale_m7_T240|r=1.0", "TTwoForty")):
            if key in sb:
                c = sb[key]
                macro(f"sys{nm}IncCpu", f"{c['incremental']['cpu_total_s']:.2f}"); macro(f"sys{nm}RepCpu", f"{c['replay_cold']['cpu_total_s']:.2f}")
                macro(f"sys{nm}IncLat", f"{c['incremental']['lat_mean_ms']:.1f}"); macro(f"sys{nm}RepLat", f"{c['replay_cold']['lat_mean_ms']:.1f}")
                macro(f"sys{nm}IncPNN", f"{c['incremental']['lat_p95_ms']:.1f}"); macro(f"sys{nm}RepPNN", f"{c['replay_cold']['lat_p95_ms']:.1f}")
                macro(f"sys{nm}IncMax", f"{c['incremental']['lat_max_ms']:.0f}"); macro(f"sys{nm}RepMax", f"{c['replay_cold']['lat_max_ms']:.0f}")
                macro(f"sys{nm}IncMem", f"{c['incremental']['peak_mem_mb']:.1f}"); macro(f"sys{nm}RepMem", f"{c['replay_cold']['peak_mem_mb']:.1f}")
        macro("sysAnswers", str(sum(c["n_answers"] for c in sb.values()))); macro("sysDisagree", str(sum(c["disagreements_inc_vs_cold"] for c in sb.values())))
    for fn, pre in (("regime_fresh_P0c.json", "rg"), ("regime_table.json", "rgOne")):
        p = os.path.join(d, fn)
        if os.path.exists(p):
            rg = json.load(open(p))
            tot = sum(rg[k]["n"] for k in rg if not k.startswith("_"))
            latest_true = sum(rg[k]["n"] for k in ("self_update", "multi_source_update", "stale_earlier") if k in rg)
            latest_wrong = sum(rg[k]["n"] for k in ("delayed_report", "low_trust_error", "other_error") if k in rg)
            macro(f"{pre}Total", str(tot)); macro(f"{pre}LatestTruePct", f"{100*latest_true/tot:.0f}"); macro(f"{pre}LatestWrongPct", f"{100*latest_wrong/tot:.0f}")
            for reg, nm in (("self_update", "Self"), ("multi_source_update", "Multi"), ("stale_earlier", "Stale"), ("delayed_report", "Delay"), ("low_trust_error", "Low"), ("other_error", "Oth"), ("retraction", "Retr")):
                c = rg[reg]; macro(f"{pre}{nm}N", str(c["n"])); macro(f"{pre}{nm}Lww", f"{c['always_commit']['world_acc']:.2f}"); macro(f"{pre}{nm}Pal", f"{c['palimpsest']['world_acc']:.2f}"); macro(f"{pre}{nm}Abst", f"{c['palimpsest']['abstain']:.2f}"); macro(f"{pre}{nm}Wrong", f"{c['palimpsest']['wrong_commit']:.2f}"); macro(f"{pre}{nm}Argmax", f"{c['palimpsest_argmax']['world_acc']:.2f}")
            rc = rg["_risk_coverage_disputed"]; macro(f"{pre}DisputedN", str(rc["n"])); macro(f"{pre}ArgmaxFull", f"{rc['argmax_full']:.3f}"); macro(f"{pre}LwwFull", f"{rc['lww_full']:.3f}")
            half = rc["curve"][len(rc["curve"]) // 2]; macro(f"{pre}HalfCov", f"{half['coverage']:.2f}"); macro(f"{pre}HalfArgmax", f"{half['accuracy']:.3f}"); macro(f"{pre}HalfLww", f"{half['lww_accuracy']:.3f}")
    p = os.path.join(d, "regime_table_poison.json")
    if os.path.exists(p):
        c = json.load(open(p))["poisoning"]; macro("rgPoisN", str(c["n"])); macro("rgPoisLww", f"{c['always_commit']['world_acc']:.2f}"); macro("rgPoisPalWrong", f"{c['palimpsest']['wrong_commit']:.2f}"); macro("rgPoisArgmax", f"{c['palimpsest_argmax']['world_acc']:.2f}")
        macro("rgPoisPalInj", f"{c['palimpsest']['latest_commit']:.2f}"); macro("rgPoisLwwInj", f"{c['always_commit']['latest_commit']:.2f}"); macro("rgPoisPalAbst", f"{c['palimpsest']['abstain']:.2f}"); macro("rgPoisArgmaxInj", f"{c['palimpsest_argmax']['latest_commit']:.2f}"); macro("rgPoisPalWorld", f"{c['palimpsest']['world_acc']:.2f}")
    for pol, nm in (("P0c", "Fa"), ("P0cSU", "Fb")):
        p = os.path.join(d, f"regime_fresh_{pol}.json")
        if os.path.exists(p):
            rg = json.load(open(p))
            for reg, rn in (("self_update", "Self"), ("delayed_report", "Delay"), ("low_trust_error", "Low"), ("other_error", "Oth")):
                c = rg[reg]["palimpsest"]; macro(f"su{nm}{rn}Abst", f"{c['abstain']:.3f}"); macro(f"su{nm}{rn}Wrong", f"{c['wrong_commit']:.3f}"); macro(f"su{nm}{rn}World", f"{c['world_acc']:.3f}")
            macro(f"su{nm}SelfN", str(rg["self_update"]["n"])); macro(f"su{nm}SelfLww", f"{rg['self_update']['always_commit']['world_acc']:.3f}")
        p = os.path.join(d, f"fresh_su_{pol}_results.json")
        if os.path.exists(p):
            r = json.load(open(p)); ps = r["per_stream"]
            (dd, lo, hi), n = bootstrap_paired([x["warranted_acc"] for x in ps["palimpsest"]], [x["warranted_acc"] for x in ps["palimpsest_noprop"]], n_boot=5000)
            macro(f"su{nm}Prop", f"{100*dd:.1f}"); macro(f"su{nm}PropLo", f"{100*lo:.1f}"); macro(f"su{nm}PropHi", f"{100*hi:.1f}"); macro(f"su{nm}WarrPerStream", f"{r['summary']['palimpsest']['n_warranted_per_stream']:.2f}")
    p = os.path.join(d, "s2", "_transitions.json")
    if os.path.exists(p):
        t = json.load(open(p))
        for sysn, nm in (("palimpsest", "Pal"), ("log_llm_adjudicator", "Log"), ("temporal_db", "Tdb")):
            c = t["transitions"][sysn]; n = c["n"]; macro(f"tr{nm}CW", f"{c.get('C->W', 0)/n:.3f}"); macro(f"tr{nm}WC", f"{c.get('W->C', 0)/n:.3f}"); macro(f"tr{nm}WW", f"{c.get('W->W', 0)/n:.3f}"); macro(f"tr{nm}Inst", f"{c['instability']/n:.3f}")
        macro("trN", str(t["transitions"]["palimpsest"]["n"]))
        pr = t["primary"]; macro("primN", str(pr["n"])); macro("primEmpty", str(pr["empty_gold"])); macro("primLogExact", f"{pr['exact']['log_llm_adjudicator']:.3f}"); macro("primLogExactNe", f"{pr['exact_nonempty']['log_llm_adjudicator']:.3f}")
    p = os.path.join(d, "oracle_validation.json")
    if os.path.exists(p):
        ov = json.load(open(p))
        macro("ovStreams", str(ov["n_streams"])); macro("ovQueries", f"{ov['n_queries']:,}".replace(",", "{,}")); macro("ovDerived", f"{ov['n_derived']:,}".replace(",", "{,}")); macro("ovDisagree", str(len(ov["disagreements"]))); macro("ovProductFail", str(len(ov["product_failures"]))); macro("ovClosureFail", str(len(ov["closure_failures"]))); macro("ovMaxEnum", str(ov["max_enumerated"])); macro("ovSkipped", str(ov["n_skipped_large"]))
    p = os.path.join(d, "holm_tests.json")
    if os.path.exists(p):
        h = json.load(open(p))
        macro("holmHThree", f"{h['H3_ece']['p_one_sided']:.3f}"); macro("holmHTwoR", f"{h['H2_crossover']['estimate']:.3f}"); macro("holmHTwoLo", f"{h['H2_crossover']['ci'][0]:.3f}"); macro("holmHTwoHi", f"{h['H2_crossover']['ci'][1]:.3f}")
        macro("holmHThreeEst", f"{h['H3_ece']['estimate']:.3f}"); macro("holmHThreeLo", f"{h['H3_ece']['ci'][0]:.3f}"); macro("holmHThreeHi", f"{h['H3_ece']['ci'][1]:.3f}")
        macro("holmHFourA", f"{h['H4a_commit']['estimate']:.3f}"); macro("holmHFourALo", f"{h['H4a_commit']['ci'][0]:.3f}"); macro("holmHFourAHi", f"{h['H4a_commit']['ci'][1]:.3f}")
        macro("holmHFourB", f"{h['H4b_resolvable_noninf']['estimate']:.3f}"); macro("holmHFourBLo", f"{h['H4b_resolvable_noninf']['ci'][0]:.3f}"); macro("holmHFourBHi", f"{h['H4b_resolvable_noninf']['ci'][1]:.3f}")
        f = h["store_vs_replay_fields"]; macro("fieldProvTwo", f"{100*(1-f['setting2_100']['provenance']):.1f}"); macro("fieldProvThree", f"{100*(1-f['setting3']['provenance']):.1f}")
        lines = ["\\begin{table}[t]\\centering\\small", "\\caption{Registered secondary hypotheses with one-sided stream-level cluster-bootstrap $p$-values (10{,}000 resamples) and Holm correction over the family $\\{$H2, H3, H4$\\}$; H4 uses the larger of its two components. Estimates are paired per-stream differences (H4) or the statistic itself (H2: $r^*$; H3: ECE(support) $-$ ECE(verbalised)).}\\label{tab:holm}",
                 "\\begin{tabular}{llccc}", "\\toprule", "Hypothesis & Statistic & Estimate [95\\% CI] & $p$ (one-sided) & Holm-adjusted \\\\", "\\midrule"]
        def pf(x): return "$<10^{-4}$" if x < 1e-4 else f"{x:.3f}"
        lines.append(f"H2 & $r^*<1$ & {h['H2_crossover']['estimate']:.3f} [{h['H2_crossover']['ci'][0]:.3f}, {h['H2_crossover']['ci'][1]:.3f}] & {pf(h['H2_crossover']['p_one_sided'])} & {pf(h['holm']['adjusted']['H2'])} \\\\")
        lines.append(f"H3 & ECE difference $<0$ & {h['H3_ece']['estimate']:.3f} [{h['H3_ece']['ci'][0]:.3f}, {h['H3_ece']['ci'][1]:.3f}] & {pf(h['H3_ece']['p_one_sided'])} & {pf(h['holm']['adjusted']['H3'])} \\\\")
        lines.append(f"H4a & commit-rate difference $<0$ & {h['H4a_commit']['estimate']:.3f} [{h['H4a_commit']['ci'][0]:.3f}, {h['H4a_commit']['ci'][1]:.3f}] & {pf(h['H4a_commit']['p_one_sided'])} & \\multirow{{2}}{{*}}{{{pf(h['holm']['adjusted']['H4'])}}} \\\\")
        lines.append(f"H4b & resolvable difference $\\ge -0.03$ & {h['H4b_resolvable_noninf']['estimate']:.3f} [{h['H4b_resolvable_noninf']['ci'][0]:.3f}, {h['H4b_resolvable_noninf']['ci'][1]:.3f}] & {pf(h['H4b_resolvable_noninf']['p_one_sided'])} & \\\\")
        lines += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
        open(os.path.join(TAB, "holm.tex"), "w").write("\n".join(lines))
    led = os.path.join(d, "anthropic_ledger.jsonl")
    if os.path.exists(led):
        tot = sum(json.loads(l).get("cost_usd", 0) for l in open(led))
        macro("spendTotal", f"{tot:.2f}")
    with open(os.path.join(TAB, "numbers.tex"), "w") as f:
        for k, v in m.items():
            f.write(f"\\newcommand{{\\{k}}}{{{v}}}\n")
    return m


if __name__ == "__main__":
    d = os.path.join(ROOT, "data")
    numbers(d)
    if os.path.exists(os.path.join(d, "setting1_results.json")):
        table_systems(os.path.join(d, "setting1_results.json"), "setting1.tex",
                      "Setting 1 (structured streams, gold dependencies, no LLM; 500 streams). Stream-level means with 95\\% cluster-bootstrap intervals.", "tab:s1")
    if os.path.exists(os.path.join(d, "setting1_results.json")):
        table_slots(os.path.join(d, "setting1_results.json"), "slots.tex")
    table_sensitivity({"P0c (main)": os.path.join(d, "setting1_results.json"), "literal P0": os.path.join(d, "setting1_P0_results.json"), "P1": os.path.join(d, "setting1_P1_results.json")}, "sensitivity.tex")
    if os.path.exists(os.path.join(d, "noise_grid", "_noise_grid.json")):
        table_noise(os.path.join(d, "noise_grid", "_noise_grid.json"), "noise.tex")
    if os.path.exists(os.path.join(d, "rq3_setting1.json")):
        table_rq3(os.path.join(d, "rq3_setting1.json"), "rq3.tex")
    if os.path.exists(os.path.join(d, "poison_setting1.json")):
        table_poison(os.path.join(d, "poison_setting1.json"), "poison.tex")
    s2 = os.path.join(d, "s2", "_results.json")
    if os.path.exists(s2):
        table_systems(s2, "setting2.tex", "Setting 2 (natural-language streams, automatic extraction with Claude Haiku 4.5; 100 streams, 99 with a warranted downstream query). Stream-level means with 95\\% cluster-bootstrap intervals; cost is measured tokens (input $+8\\times$ output) per stream.", "tab:s2",
                      cols=("warranted_acc", "warranted_direct_acc", "resolvable_acc", "unresolved_acc", "commit_rate", "prov_precision", "cost_tokens"))
    s2s = os.path.join(d, "s2_strong", "_results.json")
    if os.path.exists(s2s):
        table_systems(s2s, "setting2_strong.tex", "Sign-stability subset: 15 Setting 2 streams re-extracted and adjudicated with Claude Sonnet 4.6 on the same frozen evaluation set.", "tab:s2strong",
                      cols=("warranted_acc", "warranted_direct_acc", "resolvable_acc", "unresolved_acc", "commit_rate", "prov_precision", "cost_tokens"))
    s3 = os.path.join(d, "s3", "_results.json")
    if os.path.exists(s3):
        table_systems(s3, "setting3.tex", "Setting 3 (transfer: 30 streams assembled from Wikidata statement histories, pseudonymised surface, extraction and adjudication with Claude Haiku 4.5). Descriptive; the warranted-downstream stratum has 24 queries in 13 streams.", "tab:s3",
                      cols=("warranted_acc", "warranted_direct_acc", "resolvable_acc", "unresolved_acc", "commit_rate", "prov_precision", "cost_tokens"))
    lme = os.path.join(d, "longmemeval", "results.json")
    if os.path.exists(lme):
        table_longmemeval(lme, "longmemeval.tex")
    if os.path.exists(os.path.join(d, "regime_table.json")):
        table_regime({"main": os.path.join(d, "regime_table.json"), "poison": os.path.join(d, "regime_table_poison.json"), "fresh_p0c": os.path.join(d, "regime_fresh_P0c.json"), "fresh_su": os.path.join(d, "regime_fresh_P0cSU.json")}, "regime.tex")
        table_regime_s1(os.path.join(d, "regime_table.json"), "regime_s1.tex")
    if os.path.exists(os.path.join(d, "systems_bench.json")):
        table_systems_bench(os.path.join(d, "systems_bench.json"), "systems.tex")
    if os.path.exists(os.path.join(d, "s2", "_transitions.json")):
        table_transitions(os.path.join(d, "s2", "_transitions.json"), "transitions.tex", "Answer transitions on the non-warranted event pairs of Setting 2 (frozen gold unchanged between $\\tau-1$ and $\\tau$; micro rates over pairs). C = exact match with gold, W = not. Instability is the registered ``unsupported propagation'' metric (answer changed while gold did not); harm is C$\\to$W.", "tab:trans")
    print("tables written to", TAB, os.listdir(TAB))
