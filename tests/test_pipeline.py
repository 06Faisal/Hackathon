import pathlib
from fastapi.testclient import TestClient
from followsafe import pipeline, db
from followsafe.agents import extractor, verifier, drafter, reconciler
from followsafe.models import Task

NOTE = (pathlib.Path(__file__).parents[1] / "data/notes/P001.txt").read_text()

def test_extractor_gets_every_instruction():
    f = extractor.extract("P001", NOTE)
    assert [(m.name, m.action, m.dose) for m in f.medications] == [
        ("Furosemide", "start", "40 mg"), ("Metoprolol", "continue", "25 mg"), ("Amlodipine", "stop", None)]
    assert {x.due_date for x in f.follow_ups} == {"2026-12-02", "2026-12-09"}
    assert len(f.warnings) == 1

def test_fidelity_lock_passes_faithful_draft():
    f = extractor.extract("P001", NOTE)
    assert verifier.verify(f, drafter.draft(f)).passed

def test_fidelity_lock_blocks_changed_dose():
    f = extractor.extract("P001", NOTE); d = drafter.draft(f)
    d.text = d.text.replace("40 mg", "80 mg")
    r = verifier.verify(f, d)
    assert not r.passed and any("40 mg" in m for m in r.missing) and any("80 mg" in a for a in r.altered)

def test_fidelity_lock_blocks_dropped_warning_and_date():
    f = extractor.extract("P001", NOTE); d = drafter.draft(f)
    d.text = "\n".join(l for l in d.text.splitlines() if "Return to ER" not in l).replace("2026-12-09", "next week")
    r = verifier.verify(f, d)
    assert not r.passed and len(r.missing) == 2

def test_reconciler_flags_all_mismatch_types():
    f = extractor.extract("P001", NOTE)
    tasks = [Task(id="A", type="lab", description="Serum electrolytes (BMP) blood test", due_date="2026-12-03", authorized_by="x"),
             Task(id="B", type="imaging", description="Echocardiogram", due_date="2026-12-20", authorized_by="x")]
    s = sorted(r.status for r in reconciler.reconcile(f, tasks))
    assert s == ["date_mismatch", "missing_task", "unsupported_task"]

def test_queue_blocks_approval_of_unverified_draft_and_logs_audit():
    pipeline.run_all()
    c = TestClient(__import__("followsafe.api", fromlist=["app"]).app)
    q = c.get("/api/queue").json()
    draft = next(i for i in q if i["kind"] == "draft")
    db.conn().execute("UPDATE queue SET meta=? WHERE id=?", ('{"verify":{"passed":false}}', draft["id"])).connection.commit()
    assert c.post(f"/api/queue/{draft['id']}", json={"action": "approve"}).status_code == 409
    assert c.post(f"/api/queue/{draft['id']}", json={"action": "escalate"}).status_code == 200
    assert any(a["action"] == "escalate" for a in c.get("/api/audit").json())

def test_no_send_capability():
    import followsafe.api as api
    assert not any("send" in r.path for r in api.app.routes)

def test_fidelity_lock_blocks_dropped_action_verb():
    f = extractor.extract("P001", NOTE); d = drafter.draft(f)
    d.text = d.text.replace("Start taking Furosemide", "Furosemide")
    r = verifier.verify(f, d)
    assert not r.passed and any("start" in m for m in r.missing)

def test_combination_dose_not_flagged_and_relative_dates_match():
    from followsafe.models import ExtractedFacts, Medication, FollowUp, Draft
    f = ExtractedFacts(patient_id="X", medications=[Medication(name="Vicodin", action="take", dose="5/500 mg", source_line="")],
                       follow_ups=[FollowUp(type="appointment", description="Follow up with Dr. ABC", due_date="in two weeks", source_line="")])
    assert verifier.verify(f, Draft(patient_id="X", language="en", text="Take Vicodin 5/500 mg. Follow up with Dr. ABC in two weeks.")).passed
    t = [Task(id="A", type="appointment", description="Follow up Dr. ABC", due_date="in 2 weeks", authorized_by="x")]
    assert [r.status for r in reconciler.reconcile(f, t)] == ["matched"]

def test_grounding_blocks_misspelled_drug_from_llm():
    f = extractor.extract("P001", NOTE); f.medications[0].name = "Furomide"
    d = drafter.draft(f)
    r = verifier.verify(f, d, NOTE)
    assert not r.passed and any("not found in source note" in m for m in r.missing)
