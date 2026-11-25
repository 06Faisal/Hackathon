"""SQLite review queue + audit log (Owner: Avula Venkatesh). Nothing is ever sent.
Roles: nurse (coordinator) and doctor. Patients never act; they only see approved messages."""
import json, sqlite3, datetime, pathlib
from contextlib import closing
import os
DB = pathlib.Path("/tmp/followsafe.db") if os.getenv("VERCEL") else pathlib.Path(__file__).resolve().parents[1] / "outputs" / "followsafe.db"

ROLES = {"nurse": "Nurse coordinator", "doctor": "Doctor on duty"}
ALLOWED = {"approve": "approved", "reject": "rejected", "escalate": "escalated", "edit": "edited",
           # doctor-only task decisions on reconciliation items
           "book_task": "resolved", "use_note_date": "resolved", "keep_task_date": "resolved",
           "cancel_task": "resolved", "keep_task": "resolved"}
DOCTOR_ONLY = {"book_task": "missing_task", "use_note_date": "date_mismatch", "keep_task_date": "date_mismatch",
               "cancel_task": "unsupported_task", "keep_task": "unsupported_task"}
FINAL = ("approved", "rejected", "resolved")

PG_URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")  # set by the Neon integration on Vercel

class _Row(dict):
    """Row usable by name or by position, like sqlite3.Row."""
    def __getitem__(self, k): return list(self.values())[k] if isinstance(k, int) else dict.__getitem__(self, k)

class _PG:
    """Tiny wrapper so the sqlite-style code below runs unchanged on Postgres."""
    def __init__(self):
        import psycopg
        self.c = psycopg.connect(PG_URL)
    def execute(self, q, args=()):
        q = q.replace("?", "%s")
        ins = q.lstrip().upper().startswith("INSERT INTO QUEUE")
        if ins: q += " RETURNING id"
        cur = self.c.cursor(row_factory=lambda cur: (lambda vals: _Row(zip([d.name for d in cur.description], vals))))
        cur.execute(q, args)
        if ins:
            class _C: pass
            r = _C(); r.lastrowid = cur.fetchone()["id"]; return r
        return cur
    def __enter__(self): return self
    def __exit__(self, et, *a):
        self.c.commit() if et is None else self.c.rollback()
    def close(self): self.c.close()

_SCHEMA_DONE = False
def conn():
    global _SCHEMA_DONE
    if PG_URL:
        c = _PG()
        if not _SCHEMA_DONE:
            with c:
                for q in ["CREATE TABLE IF NOT EXISTS queue(id SERIAL PRIMARY KEY, patient_id TEXT, kind TEXT, priority INTEGER, title TEXT, body TEXT, meta TEXT, status TEXT DEFAULT 'pending_review')",
                          "CREATE TABLE IF NOT EXISTS audit(id SERIAL PRIMARY KEY, ts TEXT, item_id INTEGER, actor TEXT, action TEXT, detail TEXT)",
                          "CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT)"]:
                    c.execute(q)
            _SCHEMA_DONE = True
        return c
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    c.executescript("""
    CREATE TABLE IF NOT EXISTS queue(id INTEGER PRIMARY KEY, patient_id TEXT, kind TEXT,
      priority INTEGER, title TEXT, body TEXT, meta TEXT, status TEXT DEFAULT 'pending_review');
    CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, ts TEXT, item_id INTEGER,
      actor TEXT, action TEXT, detail TEXT);
    CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);""")
    return c

def _tx(fn):
    """Run fn(c) in one transaction and always close the file (Windows cannot reuse open files)."""
    with closing(conn()) as c:
        with c:
            return fn(c)

def reset():
    # Clear rows instead of deleting the file: Windows cannot delete a SQLite file that is still open.
    _tx(lambda c: (c.execute("DELETE FROM queue"), c.execute("DELETE FROM audit")))

def delete_patient(pid):
    _tx(lambda c: c.execute("DELETE FROM queue WHERE patient_id=?", (pid,)))

def add(patient_id, kind, priority, title, body, meta):
    def f(c):
        cur = c.execute("INSERT INTO queue(patient_id,kind,priority,title,body,meta) VALUES(?,?,?,?,?,?)",
                        (patient_id, kind, priority, title, body, json.dumps(meta)))
        log(c, cur.lastrowid, "system", "created", title)
    _tx(f)

def log(c, item_id, actor, action, detail=""):
    c.execute("INSERT INTO audit(ts,item_id,actor,action,detail) VALUES(?,?,?,?,?)",
              (datetime.datetime.now().isoformat(timespec="seconds"), item_id, actor, action, detail))

def _row(r): return dict(r) | {"meta": json.loads(r["meta"])}

def get(item_id):
    r = _tx(lambda c: c.execute("SELECT * FROM queue WHERE id=?", (item_id,)).fetchone())
    if not r: raise KeyError(item_id)
    return _row(r)

def items(status=None, patient_id=None):
    q, args = "SELECT * FROM queue WHERE 1=1", []
    if status: q += " AND status=?"; args.append(status)
    if patient_id: q += " AND patient_id=?"; args.append(patient_id)
    return [_row(r) for r in _tx(lambda c: c.execute(q + " ORDER BY priority, patient_id, id", args).fetchall())]

def stats():
    def f(c):
        by_status = {r[0]: r[1] for r in c.execute("SELECT status, COUNT(*) FROM queue GROUP BY status")}
        by_priority = {f"P{r[0]}": r[1] for r in c.execute(
            "SELECT priority, COUNT(*) FROM queue WHERE status IN ('pending_review','edited') GROUP BY priority")}
        drafts = c.execute("SELECT meta, status FROM queue WHERE kind='draft'").fetchall()
        blocked = sum(1 for r in drafts if r[1] not in FINAL and not json.loads(r[0]).get("verify", {}).get("passed", True))
        return {"total": sum(by_status.values()), "by_status": by_status, "open_by_priority": by_priority,
                "blocked_drafts": blocked, "escalated": by_status.get("escalated", 0)}
    return _tx(f)

def check(row, action, role, new_body=None):
    """All permission rules in one place. Raises PermissionError / ValueError."""
    if action not in ALLOWED: raise ValueError(f"unknown action {action}")
    if role not in ROLES: raise PermissionError("Only a nurse or a doctor can act on the queue")
    meta = row["meta"]
    if row["status"] in FINAL:
        raise PermissionError(f"Item already {row['status']} - decision is final")
    if row["status"] == "escalated" and role != "doctor":
        raise PermissionError("Escalated to the doctor - only the doctor can act on it now")
    if action in DOCTOR_ONLY:
        if role != "doctor": raise PermissionError("Only the doctor can change booked tasks")
        if row["kind"] != "action" or meta.get("status") != DOCTOR_ONLY[action]:
            raise ValueError(f"{action} does not apply to this item")
    if action == "escalate" and role == "doctor":
        raise ValueError("The doctor is the escalation point")
    if action == "edit" and row["kind"] != "draft": raise ValueError("Only draft messages can be edited")
    if action == "edit" and not (new_body or "").strip(): raise ValueError("edit needs the new message text")
    if action == "approve" and row["kind"] == "draft" and not meta.get("verify", {}).get("passed"):
        raise PermissionError("Blocked by Instruction Fidelity Lock - edit or reject instead")
    if action == "approve" and row["kind"] == "action" and meta.get("status") != "matched":
        raise PermissionError("Note and booking disagree - the doctor must decide (escalate it)")

def act(item_id, action, role, new_body=None, detail=""):
    row = get(item_id)
    check(row, action, role, new_body)
    meta, actor = row["meta"], ROLES[role]
    def f(c):
        if action == "edit":
            priority = row["priority"]
            if "facts" in meta:  # re-run the Fidelity Lock on the edited text
                from .agents import verifier
                from .models import ExtractedFacts, Draft
                v = verifier.verify(ExtractedFacts(**meta["facts"]),
                                    Draft(patient_id=row["patient_id"], language=meta.get("language", "en"), text=new_body))
                meta["verify"] = v.model_dump()
                priority = 3 if v.passed else 1
            status = "escalated" if row["status"] == "escalated" else "edited"
            c.execute("UPDATE queue SET body=?, status=?, meta=?, priority=? WHERE id=?",
                      (new_body, status, json.dumps(meta), priority, item_id))
        elif action == "escalate":
            c.execute("UPDATE queue SET status=?, priority=1 WHERE id=?", ("escalated", item_id))
        else:
            c.execute("UPDATE queue SET status=? WHERE id=?", (ALLOWED[action], item_id))
        log(c, item_id, actor, action, detail or (new_body or "")[:200])
    _tx(f)
    # Approval marks an item ready for staff to send manually; the system has no send capability.

def audit(item_id=None):
    if item_id is not None:
        return [dict(r) for r in _tx(lambda c: c.execute("SELECT * FROM audit WHERE item_id=? ORDER BY id", (item_id,)).fetchall())]
    return [dict(r) for r in _tx(lambda c: c.execute("SELECT * FROM audit ORDER BY id").fetchall())]

# ── key/value store for patients config, notes and pipeline results (persists in Postgres) ──
def kv_get(k):
    r = _tx(lambda c: c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone())
    return r["v"] if r else None

def kv_set(k, v):
    _tx(lambda c: c.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v)))

def kv_del(k=None, prefix=None):
    if prefix is not None: _tx(lambda c: c.execute("DELETE FROM kv WHERE k LIKE ?", (prefix + "%",)))
    else: _tx(lambda c: c.execute("DELETE FROM kv WHERE k=?", (k,)))
