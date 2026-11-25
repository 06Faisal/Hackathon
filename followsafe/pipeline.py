"""Agent graph orchestrator (Owner: Shaik Mohammad Junaid):
ingest -> extract -> reconcile -> draft(RAG) -> verify(Fidelity Lock) -> review queue."""
import json, pathlib, re, time
from .agents import ocr, extractor, reconciler, drafter, verifier
from .models import Task
from . import db, llm

ROOT = pathlib.Path(__file__).resolve().parents[1]
PRIORITY = {"blocked_draft": 1, "date_mismatch": 1, "missing_task": 2, "unsupported_task": 2, "draft": 3, "matched": 4}

def run_patient(pid, note_path, cfg):
    t0 = time.time(); trace = []
    note = ocr.load_note(note_path); trace.append("ingest")
    facts = extractor.extract(pid, note); trace.append("extract")
    tasks = [Task(**t) for t in cfg["tasks"]]
    recon = reconciler.reconcile(facts, tasks); trace.append("reconcile")
    d = drafter.draft(facts, cfg.get("language", "en"), cfg.get("literacy", "basic")); trace.append("draft")
    v = verifier.verify(facts, d, note); trace.append("verify")
    kind = "draft" if v.passed else "blocked_draft"
    db.add(pid, "draft", PRIORITY[kind],
           ("Draft message" if v.passed else "BLOCKED draft (Fidelity Lock)") + f" - {pid}",
           d.text, {"verify": v.model_dump(), "facts": facts.model_dump(), "sources": d.sources, "language": d.language})
    for r in recon:
        if r.status == "matched":
            title = f"Pending action: {r.description} due {r.task_date}"
        elif r.status == "date_mismatch":
            title = f"Date mismatch: {r.description} (note {r.note_date} vs task {r.task_date})"
        elif r.status == "missing_task":
            title = f"In note but no authorized task: {r.description} ({r.note_date})"
        else:
            title = f"Task not supported by note: {r.description} ({r.task_date})"
        db.add(pid, "action", PRIORITY[r.status], title, "", r.model_dump())
    trace.append("queue")
    return {"patient_id": pid, "facts": facts.model_dump(), "reconciliation": [r.model_dump() for r in recon],
            "draft": d.model_dump(), "verification": v.model_dump(), "trace": trace,
            "llm_mode": llm.MODEL if llm.available() else "offline-rule-fallback",
            "seconds": round(time.time() - t0, 3)}

RESULTS = ROOT / "outputs" / "pipeline_results.json"
SEED = ROOT / "data" / "tasks.json"            # sample data: never modified
SEED_NOTES = ROOT / "data" / "notes"
CFG = ROOT / "outputs" / "patients.json"       # live patients + booked tasks (doctor decisions land here)
NOTES = ROOT / "outputs" / "notes"             # notes for patients added in the app
PID_RE = re.compile(r"^[A-Za-z0-9_-]{1,20}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TASK_TYPES = {"lab", "appointment", "imaging", "therapy", "procedure", "other"}

def load_cfg():
    if not CFG.exists():
        CFG.parent.mkdir(exist_ok=True); CFG.write_text(SEED.read_text(encoding="utf-8"), encoding="utf-8")
    return json.loads(CFG.read_text(encoding="utf-8"))

def note_path(pid):
    p = NOTES / f"{pid}.txt"
    return p if p.exists() else SEED_NOTES / f"{pid}.txt"

def reset_demo():
    """Back to the sample data: drop added patients and doctor changes, clear the queue, re-run."""
    CFG.unlink(missing_ok=True)
    if NOTES.exists():
        for f in NOTES.glob("*.txt"): f.unlink()
    return run_all()
def save_cfg(c): CFG.write_text(json.dumps(c, indent=1, ensure_ascii=False), encoding="utf-8")
def _results(): return json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else []
def _save_results(res): RESULTS.parent.mkdir(exist_ok=True); RESULTS.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")

def run_all(reset=True):
    if reset: db.reset()
    res = [run_patient(pid, note_path(pid), cfg) for pid, cfg in load_cfg().items()]
    _save_results(res)
    return res

def run_one(pid):
    """Re-run the pipeline for one patient, replacing only that patient's queue items."""
    cfg = load_cfg()[pid]
    db.delete_patient(pid)
    r = run_patient(pid, note_path(pid), cfg)
    _save_results([x for x in _results() if x["patient_id"] != pid] + [r])
    return r

def _clean_tasks(tasks, default_by):
    out = []
    for i, t in enumerate(tasks, 1):
        desc = (t.get("description") or "").strip()
        if not desc: continue
        typ = t.get("type") or "other"
        if typ not in TASK_TYPES: raise ValueError(f"task type must be one of {sorted(TASK_TYPES)}")
        due = (t.get("due_date") or "").strip() or None
        if due and not DATE_RE.match(due): raise ValueError(f"task date must be YYYY-MM-DD: {due}")
        out.append({"id": f"T{len(out) + 1}", "type": typ, "description": desc, "due_date": due,
                    "authorized_by": (t.get("authorized_by") or "").strip() or default_by})
    return out

def add_patient(pid, note, language="en", literacy="basic", tasks=(), doctor="Doctor on duty"):
    """Save a new de-identified note + its booked tasks, then run the pipeline for that patient."""
    pid = (pid or "").strip()
    if not PID_RE.match(pid): raise ValueError("Patient ID: 1-20 letters, digits, - or _ only")
    if language not in ("en", "hi"): raise ValueError("language must be en or hi")
    if literacy not in ("basic", "standard"): raise ValueError("literacy must be basic or standard")
    if len((note or "").strip()) < 20: raise ValueError("Paste the discharge note (at least a few lines)")
    cfg = load_cfg()
    if pid in cfg or (SEED_NOTES / f"{pid}.txt").exists(): raise ValueError(f"Patient {pid} already exists")
    NOTES.mkdir(parents=True, exist_ok=True)
    NOTES.joinpath(f"{pid}.txt").write_text(note.strip() + "\n", encoding="utf-8")
    cfg[pid] = {"language": language, "literacy": literacy, "tasks": _clean_tasks(tasks, doctor)}
    save_cfg(cfg)
    return run_one(pid)

def remove_patient(pid):
    cfg = load_cfg(); cfg.pop(pid, None); save_cfg(cfg)
    NOTES.joinpath(f"{pid}.txt").unlink(missing_ok=True)
    db.delete_patient(pid)
    _save_results([x for x in _results() if x["patient_id"] != pid])

def apply_task_decision(item, action, doctor="Doctor on duty"):
    """Doctor's decision on a reconciliation item changes the booked tasks. Returns an audit detail."""
    pid, m = item["patient_id"], item["meta"]
    cfg = load_cfg(); tasks = cfg[pid]["tasks"]
    if action == "book_task":
        fu = next((f for f in next((r for r in _results() if r["patient_id"] == pid), {}).get("facts", {}).get("follow_ups", [])
                   if f["description"] == m["description"]), {})
        tid = f"T{max([int(t['id'][1:]) for t in tasks if t['id'][1:].isdigit()] + [0]) + 1}"
        tasks.append({"id": tid, "type": fu.get("type", "other"), "description": m["description"],
                      "due_date": m.get("note_date"), "authorized_by": doctor})
        detail = f"booked {tid}: {m['description']} on {m.get('note_date')}"
    elif action == "use_note_date":
        for t in tasks:
            if t["id"] == m["task_id"]: t["due_date"] = m["note_date"]
        detail = f"moved {m['task_id']} from {m['task_date']} to {m['note_date']} (note date)"
    elif action == "cancel_task":
        cfg[pid]["tasks"] = [t for t in tasks if t["id"] != m["task_id"]]
        detail = f"cancelled {m['task_id']}: {m['description']}"
    elif action == "keep_task_date":
        detail = f"kept booked date {m['task_date']}; note date {m['note_date']} overridden by doctor"
    else:  # keep_task
        detail = f"kept {m['task_id']}: {m['description']} although not in the note"
    save_cfg(cfg)
    return detail

def patient(pid):
    """Everything the UI needs for one patient: original note, facts, tasks, draft, checks."""
    r = next((x for x in _results() if x["patient_id"] == pid), None)
    cfg = load_cfg().get(pid)
    if r is None or cfg is None: raise KeyError(pid)
    note = ocr.load_note(note_path(pid))
    return r | {"note": note, "tasks": cfg["tasks"], "language": cfg.get("language", "en"), "literacy": cfg.get("literacy", "basic")}

def patients():
    return [{"patient_id": k, "language": v.get("language", "en"), "literacy": v.get("literacy", "basic"),
             "tasks": len(v["tasks"])} for k, v in load_cfg().items()]

def portal(pid):
    """What the patient will receive: only approved messages, plus their booked visits and tests."""
    cfg = load_cfg().get(pid)
    if cfg is None: raise KeyError(pid)
    msgs = [{"id": i["id"], "text": i["body"], "language": i["meta"].get("language", "en")}
            for i in db.items(status="approved", patient_id=pid) if i["kind"] == "draft"]
    # hide bookings that still have an open note/task disagreement - the patient only sees settled dates
    unsettled = {i["meta"].get("task_id") for i in db.items(patient_id=pid)
                 if i["kind"] == "action" and i["meta"].get("status") != "matched" and i["status"] not in db.FINAL}
    visits = sorted((t for t in cfg["tasks"] if t.get("due_date") and t["id"] not in unsettled), key=lambda t: t["due_date"])
    return {"patient_id": pid, "messages": msgs, "visits": visits}

if __name__ == "__main__":
    res = run_all()
    print(json.dumps(res, indent=2, ensure_ascii=False))
