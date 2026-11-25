"""FastAPI backend. Run: uvicorn followsafe.api:app --reload  then open http://localhost:8000"""
import os, pathlib
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from . import db, pipeline

app = FastAPI(title="FollowSafe", description="Human-in-the-loop follow-up coordinator. Never sends messages.")

from fastapi.responses import JSONResponse
import traceback, logging
@app.exception_handler(Exception)
async def _unhandled(request, exc):
    logging.error("Unhandled error on %s: %s", request.url.path, traceback.format_exc()[-1500:])
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"[:400]})

# Resolve static dir – try FOLLOWSAFE_ROOT env var first (set by api/index.py on Vercel),
# then walk up from __file__, then fall back to cwd.
def _find_static() -> pathlib.Path:
    env_root = os.environ.get("FOLLOWSAFE_ROOT")
    candidates = []
    if env_root:
        candidates.append(pathlib.Path(env_root) / "static")
    candidates += [
        pathlib.Path(__file__).resolve().parents[1] / "static",  # normal install
        pathlib.Path(__file__).resolve().parents[0] / "static",  # flat layout
        pathlib.Path(os.getcwd()) / "static",                    # cwd fallback
        pathlib.Path("/var/task/static"),                        # Vercel Lambda path
    ]
    for p in candidates:
        if p.exists():
            return p
    # Return best guess even if not found yet (may still work at request time)
    return candidates[0]

STATIC = _find_static()

class Action(BaseModel):
    action: str
    role: str = "nurse"          # nurse | doctor (demo role switch; real login is future work)
    body: str | None = None

class TaskIn(BaseModel):
    type: str = "other"
    description: str = ""
    due_date: str | None = None
    authorized_by: str | None = None

class PatientIn(BaseModel):
    patient_id: str
    note: str
    language: str = "en"
    literacy: str = "basic"
    tasks: list[TaskIn] = []

@app.get("/")
def index():
    html_path = STATIC / "index.html"
    # Try re-resolving at request time in case module-load path was wrong
    if not html_path.exists():
        html_path = _find_static() / "index.html"
    if not html_path.exists():
        raise HTTPException(500, f"index.html not found; STATIC={STATIC}; exists={STATIC.exists()}")
    return FileResponse(str(html_path))

@app.post("/api/run")
def run(): return pipeline.run_all()

@app.post("/api/reset-demo")
def reset_demo(): return pipeline.reset_demo()

@app.get("/api/queue")
def queue(status: str | None = None, patient_id: str | None = None):
    return db.items(status, patient_id)

@app.get("/api/stats")
def stats(): return db.stats()

@app.get("/api/patients")
def patient_list(): return pipeline.patients()

@app.post("/api/patients")
def add_patient(p: PatientIn):
    try:
        r = pipeline.add_patient(p.patient_id, p.note, p.language, p.literacy, [t.model_dump() for t in p.tasks])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "patient_id": r["patient_id"], "passed": r["verification"]["passed"],
            "flags": [x["status"] for x in r["reconciliation"] if x["status"] != "matched"]}

@app.post("/api/extract-pdf")
async def extract_pdf(request: Request):
    """Body = raw PDF bytes. Returns the note text for the nurse to review before adding the patient."""
    from .agents import ocr
    data = await request.body()
    if not data.startswith(b"%PDF"): raise HTTPException(400, "Not a PDF file")
    if len(data) > 4_000_000: raise HTTPException(413, "PDF too large (max 4 MB)")
    try: text = ocr.pdf_bytes_to_text(data)
    except ValueError as e: raise HTTPException(422, str(e))
    return {"text": text.strip()}

@app.get("/api/portal/{pid}")
def portal(pid: str):
    try: return pipeline.portal(pid)
    except KeyError: raise HTTPException(404, f"unknown patient {pid}")

@app.get("/api/patients/{pid}")
def patient(pid: str):
    try: return pipeline.patient(pid)
    except KeyError: raise HTTPException(404, f"no results for {pid} - run the pipeline first")

class VerifyIn(BaseModel):
    patient_id: str
    text: str

@app.post("/api/verify")
def verify_preview(v: VerifyIn):
    """Live Fidelity Lock check while staff edit - saves nothing."""
    from .agents import verifier
    from .models import ExtractedFacts, Draft
    p = patient(v.patient_id)
    return verifier.verify(ExtractedFacts(**p["facts"]), Draft(patient_id=v.patient_id, language=p["language"], text=v.text))

@app.post("/api/queue/{item_id}")
def act(item_id: int, a: Action):
    try:
        item = db.get(item_id)
        detail = ""
        if a.action in db.DOCTOR_ONLY:
            db.check(item, a.action, a.role)          # permission first, then change the booking
            detail = pipeline.apply_task_decision(item, a.action)
        db.act(item_id, a.action, a.role, a.body, detail)
    except PermissionError as e:
        raise HTTPException(409, str(e))
    except (KeyError, ValueError) as e:
        raise HTTPException(400, f"bad request: {e}")
    return {"ok": True}

@app.get("/api/audit")
def audit(item_id: int | None = None): return db.audit(item_id)
