"""Agent 2 - Note-Task Reconciler (Owner: Shaik Mohammad Junaid)."""
import re
from typing import List
from ..models import ExtractedFacts, Task, ReconItem

STOP = {"the","with","and","on","a","of","for","test","session","clinic","blood","follow","followup","up","visit","appointment","outpatient","office","followed","in","my","as","arranged","to","is","be"}

def _tokens(s):
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP}

def _sim(a, b, same_type=False):
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:  # generic line like "Followup" -> fall back to matching task type
        return 0.5 if same_type else 0.0
    return len(ta & tb) / max(1, min(len(ta), len(tb)))

NUM = {"one": "1", "two": "2", "three": "3", "four": "4", "a": "1", "couple": "2"}
def _when(s):
    return " ".join(NUM.get(w, w) for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in {"in", "of"})

def reconcile(facts: ExtractedFacts, tasks: List[Task]) -> List[ReconItem]:
    out, used = [], set()
    # global best-first matching instead of greedy note order
    pairs = sorted(((_sim(fu.description, t.description, fu.type == t.type), i, t) for i, fu in enumerate(facts.follow_ups)
                    for t in tasks), key=lambda x: -x[0])
    chosen = {}
    for sc, i, t in pairs:
        if sc >= 0.5 and i not in chosen and t.id not in used:
            chosen[i] = t; used.add(t.id)
    for i, fu in enumerate(facts.follow_ups):
        best = chosen.get(i)
        if best:
            same = not fu.due_date or not best.due_date or _when(fu.due_date) == _when(best.due_date)
            status = "matched" if same else "date_mismatch"
            out.append(ReconItem(status=status, description=best.description,
                                 note_date=fu.due_date, task_date=best.due_date, task_id=best.id))
        else:
            out.append(ReconItem(status="missing_task", description=fu.description, note_date=fu.due_date))
    for t in tasks:
        if t.id not in used:
            out.append(ReconItem(status="unsupported_task", description=t.description,
                                 task_date=t.due_date, task_id=t.id))
    return out
