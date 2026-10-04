# Prices $/M tokens, Batch API (50% off), verified 2 Oct 2026
P = {"gpt5mini_batch":(0.125,1.00), "haiku45_batch":(0.50,2.50), "gpt5nano_batch":(0.025,0.20)}
def cost(n_calls, tin, tout, model):
    i,o = P[model]; return (n_calls*tin*i + n_calls*tout*o)/1e6
rows=[]
def add(name, n, tin, tout, model, note=""):
    c=cost(n,tin,tout,model); rows.append((name,n,tin,tout,model,c,note)); return c
# Setting 2: NL streams
S2_streams, S2_obs, S2_q = 150, 120, 40
add("S2 paraphrase obs (naturalness)", S2_streams*S2_obs, 400, 120, "gpt5nano_batch")
add("S2 extraction+dependency (shared by all systems)", S2_streams*S2_obs, 1200, 250, "gpt5mini_batch")
add("S2 answer: PALIMPSEST (store retrieval)", S2_streams*S2_q, 1500, 150, "gpt5mini_batch")
add("S2 answer: rule-based temporal DB", S2_streams*S2_q, 1200, 150, "gpt5mini_batch")
add("S2 answer: append-only log + query-time adjudication", S2_streams*S2_q, 8500, 300, "gpt5mini_batch", "reads whole log")
add("S2 answer: Graphiti-style temporal graph (if run)", S2_streams*S2_q, 2500, 150, "gpt5mini_batch")
add("S2 ablation: verbalized confidence (extra answer pass)", S2_streams*S2_q, 1500, 200, "gpt5mini_batch")
add("S2 ablation: other 4 (no LLM re-calls; replay)", 0, 0, 0, "gpt5mini_batch")
# Setting 3: independent realistic streams
S3_streams, S3_obs, S3_q = 30, 100, 40
add("S3 extraction", S3_streams*S3_obs, 1500, 250, "gpt5mini_batch")
add("S3 answer: 3 systems", 3*S3_streams*S3_q, 4000, 200, "gpt5mini_batch")
# External checks
add("STALE subsample: 100 scenarios ingest (PALIMPSEST extraction, chunked)", 100*25, 4500, 400, "gpt5mini_batch", "100K ctx / 4K chunks")
add("STALE subsample: 300 queries x 2 systems (log baseline reads full ctx)", 300, 90000, 300, "gpt5mini_batch", "log baseline")
add("STALE subsample: 300 queries PALIMPSEST", 300, 2000, 300, "gpt5mini_batch")
add("LongMemEval KU subset: 80 items ingest + 2 systems", 80*30+160, 3500, 300, "gpt5mini_batch")
# RQ3 sampling-based confidence
add("RQ3 self-consistency k=5 on 1000 queries", 5000, 1500, 150, "gpt5mini_batch")
# Poisoning NL subset
add("Poisoning: 20 NL streams x 2 systems", 2*20*40, 3000, 200, "gpt5mini_batch")
# Backbone robustness: 20% of S2 on Haiku 4.5
add("Backbone check: 20% of S2 extraction on Haiku 4.5", int(0.2*S2_streams*S2_obs), 1200, 250, "haiku45_batch")
add("Backbone check: 20% of S2 answers, 2 systems on Haiku 4.5", int(0.2*S2_streams*S2_q)*2, 5000, 200, "haiku45_batch")
# LLM judge for free-text answers (STALE/LME only)
add("LLM judge free-text (nano)", 1000, 800, 20, "gpt5nano_batch")
# Output contract overheads (v0.3)
add("Contract: schema+vocabulary+instruction tokens on ~25k answer prompts", 25000, 600, 50, "gpt5mini_batch", "counted at full price, no cache credit")
add("Contract: vocabulary/normalisation tokens on extraction prompts", 18000, 500, 0, "gpt5mini_batch")
add("Contract: malformed-output repair, 1 attempt, <=5% of answers", 1250, 1000, 200, "gpt5mini_batch")
add("Paraphrase fidelity: independent nano cue-recovery pass", 18000, 800, 150, "gpt5nano_batch")
add("Paraphrase regeneration for flagged obs (<=15%)", 2700, 400, 120, "gpt5nano_batch")
tot=sum(r[5] for r in rows)
for r in rows: print(f"{r[0]:<70} {r[1]:>6} {r[2]:>6} {r[3]:>5} {r[4]:<15} ${r[5]:6.2f} {r[6]}")
print("-"*110); print(f"Experiments subtotal: ${tot:.2f}")
dev=10; cont=0.25*tot
print(f"Dev/prompt iteration reserve: ${dev:.2f}\nContingency (25%): ${cont:.2f}\nTOTAL: ${tot+dev+cont:.2f}  of $100")
# sanity: full STALE on Haiku non-batch
print("\nFull STALE 1200 q x 100K ctx on Haiku 4.5 (non-batch):", cost(1200,100000,300,"haiku45_batch")*2, "USD")
