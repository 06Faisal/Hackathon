"""Run FollowSafe on real MTSamples discharge notes and score against hand-written answer keys."""
import json, pathlib
from followsafe import pipeline, db, llm

D = pathlib.Path("data/mtsamples")
keys = json.loads((D / "answer_keys.json").read_text())
cfgs = json.loads((D / "tasks.json").read_text())
db.reset(); res, rows = [], []
for pid, cfg in cfgs.items():
    r = pipeline.run_patient(pid, D / f"{pid}.txt", cfg); res.append(r)
    k, f = keys[pid], r["facts"]
    names = " | ".join(m["name"].lower() for m in f["medications"])
    hit = [m for m in k["meds"] if m in names or (m == "kcl" and "potassium" in names) or (m == "multivitamin" and "vitamin" in names)]
    rows.append({"note": pid, "med_recall": f"{len(hit)}/{len(k['meds'])}", "meds_missed": sorted(set(k["meds"]) - set(hit)),
                 "followups": f"{len(f['follow_ups'])} found / {k['followups']} expected",
                 "warnings": f"{len(f['warnings'])} found / {k['warnings']} expected",
                 "lock_passed": r["verification"]["passed"],
                 "lock_reasons": r["verification"]["missing"] + r["verification"]["altered"],
                 "flags": [f"{x['status']}: {x['description']}" for x in r["reconciliation"] if x["status"] != "matched"],
                 "seconds": r["seconds"]})
tot = sum(len(keys[p]["meds"]) for p in keys); got = sum(int(r["med_recall"].split("/")[0]) for r in rows)
out = {"llm_mode": res[0]["llm_mode"], "notes": len(rows), "overall_med_recall": f"{got}/{tot}", "per_note": rows}
pathlib.Path("outputs/mtsamples_results.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
pathlib.Path("outputs/mtsamples_evaluation.json").write_text(json.dumps(out, indent=2))
print(json.dumps(out, indent=2))
