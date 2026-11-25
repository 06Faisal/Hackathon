"""Agent 3 - Patient Message Drafter with RAG (Owner: P Sai Eshwar Reddy)."""
from .. import llm
from ..models import ExtractedFacts, Draft
from .rag import Retriever

PROMPT = """Write a short, warm follow-up message for a patient (literacy: {lit}, language: {lang}).
Use the approved hospital wording below where it fits. You MUST include every medicine name,
dose, frequency, duration, date and warning EXACTLY as given - do not round, convert or omit.
Do not add medical advice that is not in the facts.
APPROVED WORDING:
{kb}
FACTS (JSON):
{facts}"""

ACTION_WORD = {"start": "Start taking", "continue": "Keep taking", "increase": "Increase",
               "decrease": "Reduce", "stop": "Stop taking", "take": "Take"}
HEADINGS = {"en": ("Your medicines", "Your next tests and visits", "Warning signs"),
            "hi": ("आपकी दवाइयाँ (Your medicines)", "आपकी अगली जाँच और विज़िट (Your next tests and visits)",
                   "खतरे के संकेत (Warning signs)")}

_retriever = None
def retriever():
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
    return _retriever

def draft(facts: ExtractedFacts, language="en", literacy="basic") -> Draft:
    query = " ".join([m.name + " " + m.action for m in facts.medications] +
                     [f.description for f in facts.follow_ups] + [w.text for w in facts.warnings])
    kb = retriever().search(query, k=4)
    if llm.available():
        text = llm.generate_text(PROMPT.format(lit=literacy, lang=language,
                                               kb="\n".join(d["text"] for d in kb),
                                               facts=facts.model_dump_json(indent=1)))
        return Draft(patient_id=facts.patient_id, language=language, text=text, sources=[d["id"] for d in kb])
    h = HEADINGS.get(language, HEADINGS["en"])
    lines = ["Dear patient,", "Thank you for visiting us. Here is a summary of what your doctor asked you to do."]
    tpl = {d["id"]: d["text"] for d in kb}
    if facts.medications:
        lines += ["", f"{h[0]}:"]
        if "TPL-MED" in tpl: lines.append(tpl["TPL-MED"])
        for m in facts.medications:
            parts = [ACTION_WORD[m.action], m.name]
            if m.action == "increase" and m.dose: parts += ["to", m.dose]
            elif m.dose: parts.append(m.dose)
            if m.frequency: parts.append(m.frequency)
            if m.duration: parts.append("for " + m.duration)
            lines.append("- " + " ".join(parts) + ".")
    if facts.follow_ups:
        lines += ["", f"{h[1]}:"]
        for f in facts.follow_ups:
            lines.append(f"- {f.description}" + (f" on {f.due_date}." if f.due_date else "."))
    if facts.warnings:
        lines += ["", f"{h[2]}:"]
        if "TPL-WARN" in tpl: lines.append(tpl["TPL-WARN"])
        lines += [f"- {w.text}" for w in facts.warnings]
    edu = [d for d in kb if d["id"].startswith("EDU")]
    if edu: lines += ["", edu[0]["text"]]
    lines += ["", "If you have questions, please call the care coordination desk."]
    return Draft(patient_id=facts.patient_id, language=language, text="\n".join(lines),
                 sources=[d["id"] for d in kb])
