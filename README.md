# FollowSafe - PS 72 Hospital Follow-up Communication Coordinator (Review 2 prototype)

Agent pipeline: ingest/OCR -> Fact Extractor -> Note-Task Reconciler -> Drafter (RAG) -> Instruction Fidelity Lock -> human review queue.
**The system has no send function.** Every item needs staff approval; drafts that fail the Fidelity Lock cannot be approved.

```
pip install -r requirements.txt
export GEMINI_API_KEY=...        # optional; without it a deterministic offline extractor/drafter is used
python -m followsafe.pipeline    # run on sample patients -> outputs/pipeline_results.json
python evaluate.py               # initial testing -> outputs/evaluation.json
pytest -q                        # 7 unit/integration tests
uvicorn followsafe.api:app       # review UI at http://localhost:8000
```

| Module | Owner |
|---|---|
| agents/extractor.py, agents/verifier.py | Shaik Faisal Ahmed |
| pipeline.py, agents/reconciler.py | Shaik Mohammad Junaid |
| agents/drafter.py, agents/rag.py, data/kb | P Sai Eshwar Reddy |
| db.py, api.py, static/index.html | Avula Venkatesh |

**Gemini mode:** `export GEMINI_API_KEY=<your key>` and optionally `export GEMINI_MODEL=gemini-3.5-flash-lite`
(free tier allows ~20 requests/day per model; each patient uses 2). Never commit the key.

**Real-data and OCR tests**
```
python run_mtsamples.py        # 6 real MTSamples discharge notes -> outputs/mtsamples_evaluation.json (12 Gemini requests)
python rescore_mtsamples.py    # re-score saved Gemini output after code changes (no API calls)
```
`data/scanned/MT-KNEE_scanned.pdf` is an image-only scan for the OCR path; result in `outputs/scanned_pdf_result.json`.

## Review API (for the frontend)
| Method | Path | Purpose |
|---|---|---|
| POST | /api/run | Run pipeline on sample patients (resets queue) |
| GET | /api/queue?status=&patient_id= | Queue, sorted P1 first, optional filters |
| POST | /api/queue/{id} | `{"action": "approve"\|"edit"\|"reject"\|"escalate", "actor", "body"}` - edit re-runs the Fidelity Lock; blocked drafts can't be approved (409); approve/reject are final |
| GET | /api/patients/{pid} | Original note, extracted facts, tasks, draft, verification, reconciliation |
| POST | /api/verify | `{"patient_id", "text"}` live Fidelity Lock check while editing, saves nothing |
| GET | /api/stats | Counts by status / open priority, blocked drafts |
| GET | /api/audit?item_id= | Audit log, optionally for one item |
