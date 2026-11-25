"""Agent 1 - Fact Extractor (Owner: Shaik Faisal Ahmed)."""
import re
from .. import llm
from ..models import ExtractedFacts, Medication, FollowUp, Warning

PROMPT = """You are a clinical fact extractor. From the plan, discharge instructions, discharge
medications and follow-up sections of this de-identified visit note, extract EVERY medication
instruction the patient must follow after discharge (including hold / resume / stop), every
follow-up (lab/appointment/imaging/therapy/procedure) and every warning sign to report.
Copy doses, frequencies, durations and timing words EXACTLY as written (keep abbreviations such as
b.i.d. or q.4-6h; keep relative timing such as "in two weeks" as due_date). For a held medicine use
action "stop" and put the hold period in duration. Include the verbatim source_line.
Do not infer anything not written.
NOTE:
{note}"""

DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
DOSE = re.compile(r"(\d+(?:\.\d+)?\s?(?:mg|mcg|g|units|ml))", re.I)
FREQ = re.compile(r"(once daily(?: in the morning)?|twice daily(?: with meals)?|three times daily|every \d+ hours(?: as needed)?)", re.I)
DUR = re.compile(r"for (\d+ (?:days|weeks))", re.I)
ACTIONS = {"start": "start", "continue": "continue", "increase": "increase",
           "decrease": "decrease", "reduce": "decrease", "stop": "stop"}
FU_KEYS = [("lab", r"blood test|lab|hba1c|electrolytes"), ("imaging", r"screening|scan|x-ray|echo|mri|ct\b"),
           ("therapy", r"physiotherapy"), ("procedure", r"suture|wound check"),
           ("appointment", r"appointment|clinic|examination|follow-up")]

def _plan_lines(note: str):
    plan = note.split("PLAN:", 1)[-1]
    items, numbered = [], False
    for raw in plan.splitlines():
        raw = raw.strip()
        if not raw: continue
        if re.match(r"^\d+\.\s*", raw):          # new numbered item
            numbered = True; items.append(re.sub(r"^\d+\.\s*", "", raw))
        elif numbered and items and not items[-1].endswith("."):
            items[-1] += " " + raw                  # PDF line-wrap: continuation of the previous item
        else:
            items.append(raw)
    yield from (i for i in items if i)

def _rule_extract(pid: str, note: str) -> ExtractedFacts:
    f = ExtractedFacts(patient_id=pid)
    for ln in _plan_lines(note):
        low = ln.lower()
        if re.search(r"return to er|seek urgent|immediately if|weigh yourself", low):
            f.warnings.append(Warning(text=ln, source_line=ln)); continue
        first = low.split()[0]
        drug = re.search(r"([A-Z][a-z]+)\b(?=.*(?:\d+\s?mg|\.$))", ln)
        if first in ACTIONS or (DOSE.search(ln) and not DATE.search(ln)):
            nm = re.search(r"(?:Start|Continue|Increase|Decrease|Reduce|Stop)?\s*([A-Z][A-Za-z0-9-]+)", ln)
            name = nm.group(1) if nm else ln.split()[min(1, len(ln.split()) - 1)].strip(".,").title()
            m = Medication(name=name, action=ACTIONS.get(first, "take"),
                           dose=(DOSE.search(ln).group(1) if DOSE.search(ln) else None),
                           frequency=(FREQ.search(ln).group(1) if FREQ.search(ln) else None),
                           duration=(DUR.search(ln).group(1) if DUR.search(ln) else None),
                           source_line=ln)
            f.medications.append(m); continue
        d = DATE.search(ln)
        for t, pat in FU_KEYS:
            if re.search(pat, low):
                desc = re.sub(r"\s*(on|by)\s*\d{4}-\d{2}-\d{2}\.?", "", ln).rstrip(".")
                f.follow_ups.append(FollowUp(type=t, description=desc,
                                             due_date=d.group(0) if d else None, source_line=ln))
                break
    return f

def extract(pid: str, note: str) -> ExtractedFacts:
    if llm.available():
        data = llm.generate_json(PROMPT.format(note=note), ExtractedFacts)
        data["patient_id"] = pid
        return ExtractedFacts(**data)
    return _rule_extract(pid, note)
