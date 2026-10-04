"""RQ1 — accuracy–cost curves and the write-time vs query-time crossover (Setting 2).

Cost model (tokens, input + 8*output, per stream): PALIMPSEST pays extraction once per
observation (write time) and nothing per query; the raw-NL log pays nothing at write time
and a full-context adjudication per query; the extracted-claims log pays both. For a
query-to-update ratio r (queries per observation):
    cost_PAL(r)   = E                      (E = extraction tokens per stream)
    cost_NL(r)    = r * n_obs * A_nl       (A = adjudication tokens per query)
    cost_LOG(r)   = E + r * n_obs * A_log
Crossover r* (where the NL log becomes dearer than write-time extraction) = E / (n_obs * A_nl).
Accuracy is per system, measured; at matched cost the comparison is read off the curves.
Usage: python scripts/crossover.py data/s2/_results.json [--ratios 0.1,0.33,1.0]
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main(path, ratios=(0.1, 0.33, 1.0)):
    r = json.load(open(path))["per_stream"]
    def mean(name, k):
        xs = [x[k] for x in r[name] if x.get(k) is not None]
        return sum(xs) / len(xs) if xs else float("nan")
    E = mean("palimpsest", "cost_tokens")
    n_obs = mean("palimpsest", "n_obs")
    A_nl = mean("log_nl_adjudicator", "adj_tokens_per_query") if "log_nl_adjudicator" in r else float("nan")
    A_log = mean("log_llm_adjudicator", "adj_tokens_per_query") if "log_llm_adjudicator" in r else float("nan")
    out = {"E_extraction_tokens_per_stream": E, "n_obs": n_obs, "A_nl_tokens_per_query": A_nl, "A_log_tokens_per_query": A_log,
           "r_star_nl": E / (n_obs * A_nl) if A_nl == A_nl else None, "curves": []}
    print(f"E={E:.0f} tokens/stream, n_obs={n_obs:.0f}, A_nl={A_nl:.0f}, A_log={A_log:.0f} tokens/query; r* (NL log) = {out['r_star_nl']:.3f} queries per observation")
    for rr in ratios:
        row = {"ratio": rr,
               "palimpsest": {"cost": E, "warranted_acc": mean("palimpsest", "warranted_acc"), "resolvable_acc": mean("palimpsest", "resolvable_acc")},
               "log_nl": {"cost": rr * n_obs * A_nl, "warranted_acc": mean("log_nl_adjudicator", "warranted_acc"), "resolvable_acc": mean("log_nl_adjudicator", "resolvable_acc")},
               "log_llm": {"cost": E + rr * n_obs * A_log, "warranted_acc": mean("log_llm_adjudicator", "warranted_acc"), "resolvable_acc": mean("log_llm_adjudicator", "resolvable_acc")}}
        out["curves"].append(row)
        print(f"ratio {rr}: PAL cost {E:.0f} acc {row['palimpsest']['warranted_acc']:.3f} | NL-log cost {row['log_nl']['cost']:.0f} acc {row['log_nl']['warranted_acc']:.3f} | claims-log cost {row['log_llm']['cost']:.0f} acc {row['log_llm']['warranted_acc']:.3f}")
    json.dump(out, open(os.path.join(os.path.dirname(path), "_crossover.json"), "w"), indent=1)
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    ratios = tuple(float(x) for x in a[a.index("--ratios") + 1].split(",")) if "--ratios" in a else (0.1, 0.33, 1.0)
    main(a[0], ratios)
