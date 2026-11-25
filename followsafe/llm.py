"""LLM client. Uses Gemini 2.5 Flash when GEMINI_API_KEY is set; otherwise a
deterministic offline fallback so the prototype runs without network/API key."""
import json, os, time

import hashlib
_client = None
def _cli():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options={"api_version": "v1beta", "timeout": 20000})
    return _client

def _cached(kind, prompt, fn):
    """Same note + same prompt -> reuse the earlier Gemini answer (fast demos, fewer API calls)."""
    from . import db
    k = f"llm:{kind}:{MODEL}:" + hashlib.sha256(prompt.encode()).hexdigest()
    try:
        hit = db.kv_get(k)
        if hit is not None: return hit
    except Exception: pass
    out = fn()
    try: db.kv_set(k, out)
    except Exception: pass
    return out

_FAST = {"thinking_config": {"thinking_budget": 0}}  # no "thinking" pass: much lower latency

def _retry(fn, tries=2):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            if i == tries - 1 or "RESOURCE_EXHAUSTED" in str(e) or not any(c in str(e) for c in ("503", "UNAVAILABLE")):
                raise
            time.sleep(1 + i)


MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

_down_until = 0.0
def available() -> bool:
    """Gemini is used only when a key is set and it has not just failed (quota/outage)."""
    return bool(os.getenv("GEMINI_API_KEY")) and time.time() >= _down_until

def mark_down(seconds=300):
    """Circuit breaker: after a Gemini failure use the offline engine for a while instead of retrying every call."""
    global _down_until
    _down_until = time.time() + seconds

def generate_json(prompt: str, schema) -> dict:
    def call():
        resp = _retry(lambda: _cli().models.generate_content(
            model=MODEL, contents=prompt,
            config={"response_mime_type": "application/json", "response_schema": schema,
                    "temperature": 0, **_FAST}))
        return resp.text
    return json.loads(_cached("json", prompt, call))

def generate_text(prompt: str) -> str:
    return _cached("text", prompt, lambda: _retry(lambda: _cli().models.generate_content(
        model=MODEL, contents=prompt, config={"temperature": 0.2, **_FAST})).text)

def pdf_to_text(data: bytes) -> str:
    """Read a (scanned) PDF with Gemini. Used only when the PDF has no text layer."""
    from google.genai import types
    resp = _retry(lambda: _cli().models.generate_content(model=MODEL, contents=[
        types.Part.from_bytes(data=data, mime_type="application/pdf"),
        "Transcribe this clinical note exactly as plain text. Do not summarise or add anything."],
        config={"temperature": 0, **_FAST}))
    return resp.text
