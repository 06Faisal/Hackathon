"""Agent 4 - Instruction Fidelity Lock (Owner: Shaik Faisal Ahmed).
Deterministic check: every drug name, dose, frequency, duration, date and warning
in the extracted facts must appear verbatim in the draft; no new doses/dates may appear."""
import re
from ..models import ExtractedFacts, Draft, VerifyResult

DOSE = re.compile(r"\d+(?:\.\d+)?\s?(?:mg|mcg|g|units|ml)\b", re.I)
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
VERBS = {"start": ["start", "begin", "new"], "stop": ["stop", "discontinue"],
         "increase": ["increase", "raise"], "decrease": ["reduce", "decrease", "lower"]}
norm = lambda s: re.sub(r"\s+", " ", s.lower()).strip()

def verify(facts: ExtractedFacts, draft: Draft, note: str | None = None) -> VerifyResult:
    t = norm(draft.text)
    missing = []
    if note is not None:  # grounding: extracted facts must exist in the source note
        src = norm(note.replace("-\n", ""))
        for m in facts.medications:
            for label, v in [("drug", m.name), ("dose", m.dose)]:
                if v and label == "drug" and v.lower() in {"home medications", "home meds"}:
                    continue
                if v and norm(v) not in src:
                    missing.append(f"{m.name}: {label} '{v}' not found in source note")
    for m in facts.medications:
        for label, v in [("drug", m.name), ("dose", m.dose), ("frequency", m.frequency), ("duration", m.duration)]:
            if v and norm(v) not in t:
                missing.append(f"{m.name}: {label} '{v}'")
        verbs = VERBS.get(m.action)
        if verbs:
            lines = [l for l in t.splitlines() if norm(m.name) in l]
            if not any(any(v in l for v in verbs) for l in lines):
                missing.append(f"{m.name}: '{m.action}' instruction")
    for f in facts.follow_ups:
        if f.due_date and f.due_date not in t:
            missing.append(f"{f.description}: date {f.due_date}")
    for w in facts.warnings:
        if norm(w.text) not in t:
            missing.append(f"warning '{w.text[:50]}...'")
    allowed_doses = {norm(m.dose) for m in facts.medications if m.dose}
    allowed_dates = {f.due_date for f in facts.follow_ups if f.due_date}
    allowed_text = " ".join(allowed_doses)
    altered = [f"unsupported dose '{d}'" for d in {norm(x) for x in DOSE.findall(draft.text)}
               if d not in allowed_text]  # '500 mg' is allowed inside '5/500 mg' 
    altered += [f"unsupported date '{d}'" for d in set(DATE.findall(draft.text)) if d not in allowed_dates]
    return VerifyResult(passed=not missing and not altered, missing=missing, altered=altered)
