"""Add patient, nurse/doctor/patient roles, doctor task decisions."""
import pytest
from fastapi.testclient import TestClient
from followsafe import pipeline
from followsafe.api import app

c = TestClient(app)
NOTE = """PROGRESS NOTE (de-identified)
Patient ID: TST1  Specialty: Cardiology
PLAN:
1. Start Aspirin 75 mg once daily.
2. Lipid profile blood test on 2027-01-10.
3. Cardiology clinic follow-up on 2027-01-20.
4. Return to ER immediately if chest pain."""

@pytest.fixture(autouse=True)
def fresh():
    pipeline.reset_demo()
    yield
    pipeline.reset_demo()

def post(i, action, role="nurse", body=None):
    return c.post(f"/api/queue/{i}", json={"action": action, "role": role, "body": body})

def items(pid): return c.get("/api/queue", params={"patient_id": pid}).json()
def flag(pid, status): return next(i for i in items(pid) if i["kind"] == "action" and i["meta"]["status"] == status)

def test_add_patient_runs_pipeline_and_flags_gaps():
    r = c.post("/api/patients", json={"patient_id": "TST1", "note": NOTE, "language": "en", "literacy": "basic",
               "tasks": [{"type": "lab", "description": "Lipid profile blood test", "due_date": "2027-01-12"},
                         {"type": "imaging", "description": "Chest X-ray", "due_date": "2027-01-05"}]})
    assert r.status_code == 200 and r.json()["passed"]
    assert sorted(r.json()["flags"]) == ["date_mismatch", "missing_task", "unsupported_task"]
    assert any(p["patient_id"] == "TST1" for p in c.get("/api/patients").json())
    assert len(items("P001")) > 0          # other patients untouched

def test_add_patient_validation():
    bad = [{"patient_id": "../x", "note": NOTE}, {"patient_id": "P001", "note": NOTE},
           {"patient_id": "TST1", "note": "short"}, {"patient_id": "TST1", "note": NOTE, "language": "fr"},
           {"patient_id": "TST1", "note": NOTE, "tasks": [{"description": "x", "due_date": "20 Jan"}]}]
    for b in bad: assert c.post("/api/patients", json=b).status_code == 400, b

def test_nurse_cannot_resolve_mismatch_but_can_escalate():
    m = flag("P003", "date_mismatch")
    assert post(m["id"], "approve").status_code == 409
    assert post(m["id"], "use_note_date").status_code == 409          # doctor only
    assert post(m["id"], "escalate").status_code == 200
    assert post(m["id"], "reject").status_code == 409                 # now the doctor's
    assert post(m["id"], "use_note_date", "doctor").status_code == 200
    t = next(t for t in pipeline.load_cfg()["P003"]["tasks"] if t["id"] == m["meta"]["task_id"])
    assert t["due_date"] == m["meta"]["note_date"]
    assert post(m["id"], "approve", "doctor").status_code == 409      # final

def test_doctor_books_missing_task_and_cancels_unsupported():
    c.post("/api/patients", json={"patient_id": "TST1", "note": NOTE,
           "tasks": [{"type": "imaging", "description": "Chest X-ray", "due_date": "2027-01-05"}]})
    miss = flag("TST1", "missing_task"); uns = flag("TST1", "unsupported_task")
    assert post(miss["id"], "book_task", "doctor").status_code == 200
    assert post(uns["id"], "cancel_task", "doctor").status_code == 200
    assert post(uns["id"], "book_task", "doctor").status_code == 409  # already resolved
    descs = [t["description"] for t in pipeline.load_cfg()["TST1"]["tasks"]]
    assert miss["meta"]["description"] in descs and "Chest X-ray" not in descs
    acts = [a["actor"] for a in c.get("/api/audit", params={"item_id": miss["id"]}).json()]
    assert "Doctor on duty" in acts

def test_wrong_action_for_item_and_unknown_role():
    m = flag("P001", "unsupported_task")
    assert post(m["id"], "book_task", "doctor").status_code == 400
    assert post(m["id"], "escalate", "patient").status_code == 409
    assert post(m["id"], "escalate", "doctor").status_code == 400

def test_patient_portal_shows_only_approved_and_settled():
    d = next(i for i in items("P001") if i["kind"] == "draft")
    p = c.get("/api/portal/P001").json()
    assert p["messages"] == []
    assert all(v["description"] != "Echocardiogram" for v in p["visits"])   # unsupported, still open
    assert post(d["id"], "approve").status_code == 200
    p = c.get("/api/portal/P001").json()
    assert len(p["messages"]) == 1 and "Furosemide" in p["messages"][0]["text"]
    assert c.get("/api/portal/NOPE").status_code == 404

def test_escalated_draft_doctor_edits_and_approves():
    d = next(i for i in items("P002") if i["kind"] == "draft")
    assert post(d["id"], "escalate").status_code == 200
    bad = d["body"].replace("Increase", "").replace("increase", "")
    assert post(d["id"], "edit", "nurse", bad).status_code == 409
    assert post(d["id"], "edit", "doctor", bad).status_code == 200
    assert post(d["id"], "approve", "doctor").status_code == 409      # lock still blocks the doctor
    assert post(d["id"], "edit", "doctor", d["body"]).status_code == 200
    assert post(d["id"], "approve", "doctor").status_code == 200

def test_sample_data_never_changes_and_reset_restores():
    seed = pipeline.SEED.read_text()
    m = flag("P003", "date_mismatch"); post(m["id"], "escalate"); post(m["id"], "use_note_date", "doctor")
    c.post("/api/patients", json={"patient_id": "TST1", "note": NOTE})
    assert pipeline.SEED.read_text() == seed
    c.post("/api/reset-demo")
    assert "TST1" not in pipeline.load_cfg() and pipeline.load_cfg() == __import__("json").loads(seed)
    assert flag("P003", "date_mismatch")["status"] == "pending_review"
