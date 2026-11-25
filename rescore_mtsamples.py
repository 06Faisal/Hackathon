"""Re-run reconciler + Fidelity Lock on saved Gemini outputs (no new API calls)."""
import json
from followsafe.models import ExtractedFacts, Draft, Task
from followsafe.agents import reconciler, verifier
res = json.load(open("outputs/mtsamples_results.json")); cfgs = json.load(open("data/mtsamples/tasks.json"))
ev = json.load(open("outputs/mtsamples_evaluation.json"))
for r, row in zip(res, ev["per_note"]):
    f = ExtractedFacts(**r["facts"])
    r["reconciliation"] = [x.model_dump() for x in reconciler.reconcile(f, [Task(**t) for t in cfgs[r["patient_id"]]["tasks"]])]
    r["verification"] = verifier.verify(f, Draft(**r["draft"]), open(f"data/mtsamples/{r['patient_id']}.txt").read()).model_dump()
    row["lock_passed"] = r["verification"]["passed"]
    row["lock_reasons"] = r["verification"]["missing"] + r["verification"]["altered"]
    row["flags"] = [f"{x['status']}: {x['description']}" for x in r["reconciliation"] if x["status"] != "matched"]
json.dump(res, open("outputs/mtsamples_results.json", "w"), indent=2, ensure_ascii=False)
json.dump(ev, open("outputs/mtsamples_evaluation.json", "w"), indent=2)
for row in ev["per_note"]: print(row["note"], row["lock_passed"], row["lock_reasons"], row["flags"])
