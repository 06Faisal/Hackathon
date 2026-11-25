"""Initial testing: field-level extraction accuracy vs answer keys + robustness of Fidelity Lock."""
import json, random, re
from followsafe import pipeline
from followsafe.agents import extractor, drafter, verifier

KEYS = {"P001": {"meds": 3, "dates": {"2026-12-02", "2026-12-09"}, "warnings": 1},
        "P002": {"meds": 2, "dates": {"2027-02-20", "2026-12-15"}, "warnings": 1},
        "P003": {"meds": 2, "dates": {"2026-11-28", "2026-12-05"}, "warnings": 1}}
EXPECTED_FLAGS = {("P001", "unsupported_task"), ("P002", "missing_task"), ("P003", "date_mismatch")}

res = pipeline.run_all()
rows, flags = [], set()
for r in res:
    k, f = KEYS[r["patient_id"]], r["facts"]
    rows.append({"patient": r["patient_id"],
                 "meds": f"{len(f['medications'])}/{k['meds']}",
                 "dates": f"{len({x['due_date'] for x in f['follow_ups']} & k['dates'])}/{len(k['dates'])}",
                 "warnings": f"{len(f['warnings'])}/{k['warnings']}",
                 "draft_verified": r["verification"]["passed"], "seconds": r["seconds"]})
    flags |= {(r["patient_id"], x["status"]) for x in r["reconciliation"] if x["status"] != "matched"}

# Fault injection: corrupt faithful drafts the way an LLM might, check the lock catches every one
random.seed(7); caught = total = 0
mutations = [lambda t: re.sub(r"(\d+) mg", lambda m: f"{int(m.group(1))*2} mg", t, count=1),
             lambda t: re.sub(r"\d{4}-\d{2}-(\d{2})", lambda m: m.group(0)[:-2] + f"{(int(m.group(1))%28)+1:02d}", t, count=1),
             lambda t: "\n".join(l for l in t.splitlines() if "immediately if" not in l and "urgent care" not in l),
             lambda t: t.replace("twice daily", "once daily", 1),
             lambda t: t.replace("Stop taking", "Keep taking", 1)]
from followsafe.models import ExtractedFacts, Draft
for r in res:  # reuse pipeline outputs - no extra LLM calls
    facts = ExtractedFacts(**r["facts"])
    for mut in mutations:
        d = Draft(**r["draft"]); new = mut(d.text)
        if new == d.text: continue
        d.text = new; total += 1; caught += not verifier.verify(facts, d).passed

report = {"llm_mode": res[0]["llm_mode"], "extraction": rows,
          "mismatch_flags_found": sorted(flags), "mismatch_recall": f"{len(flags & EXPECTED_FLAGS)}/{len(EXPECTED_FLAGS)}",
          "fidelity_lock_fault_injection": f"{caught}/{total} corrupted drafts blocked"}
json.dump(report, open("outputs/evaluation.json", "w"), indent=2)
json.dump(res, open("outputs/pipeline_results.json", "w"), indent=2, ensure_ascii=False)
print(json.dumps(report, indent=2))
