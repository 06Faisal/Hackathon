from fastapi.testclient import TestClient
from followsafe import pipeline
from followsafe.api import app

c = TestClient(app)

def _p002_draft():
    pipeline.run_all()
    return next(i for i in c.get("/api/queue", params={"patient_id": "P002"}).json() if i["kind"] == "draft")

def test_edit_reverifies_and_unblocks():
    d = _p002_draft()
    bad = d["body"].replace("Increase", "").replace("increase", "")
    assert c.post(f"/api/queue/{d['id']}", json={"action": "edit", "body": bad}).status_code == 200
    assert c.post(f"/api/queue/{d['id']}", json={"action": "approve"}).status_code == 409
    assert c.post(f"/api/queue/{d['id']}", json={"action": "edit", "body": d["body"]}).status_code == 200
    assert c.post(f"/api/queue/{d['id']}", json={"action": "approve"}).status_code == 200

def test_decisions_are_final_and_edit_needs_text():
    d = _p002_draft()
    assert c.post(f"/api/queue/{d['id']}", json={"action": "edit", "body": " "}).status_code == 400
    c.post(f"/api/queue/{d['id']}", json={"action": "reject"})
    assert c.post(f"/api/queue/{d['id']}", json={"action": "approve"}).status_code == 409

def test_escalate_goes_to_top():
    pipeline.run_all()
    item = next(i for i in c.get("/api/queue").json() if i["priority"] == 3)
    c.post(f"/api/queue/{item['id']}", json={"action": "escalate"})
    assert next(i for i in c.get("/api/queue").json() if i["id"] == item["id"])["priority"] == 1

def test_patient_detail_verify_preview_stats_audit():
    d = _p002_draft()
    p = c.get("/api/patients/P002").json()
    assert "PLAN" in p["note"] and p["facts"]["medications"] and p["tasks"]
    assert c.get("/api/patients/NOPE").status_code == 404
    assert c.post("/api/verify", json={"patient_id": "P002", "text": d["body"]}).json()["passed"]
    assert not c.post("/api/verify", json={"patient_id": "P002", "text": "hello"}).json()["passed"]
    s = c.get("/api/stats").json()
    assert s["total"] == len(c.get("/api/queue").json())
    assert all(a["item_id"] == d["id"] for a in c.get("/api/audit", params={"item_id": d["id"]}).json())
