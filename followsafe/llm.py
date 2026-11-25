"""LLM client. Uses Gemini 2.5 Flash when GEMINI_API_KEY is set; otherwise a
deterministic offline fallback so the prototype runs without network/API key."""
import json, os, time

def _retry(fn, tries=5):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            if i == tries - 1 or not any(c in str(e) for c in ("503", "429", "UNAVAILABLE")):
                raise
            time.sleep(2 ** i * 2)


MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

def available() -> bool:
    return bool(os.getenv("GEMINI_API_KEY"))

def generate_json(prompt: str, schema) -> dict:
    from google import genai  # pip install google-genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options={"api_version": "v1beta"})
    resp = _retry(lambda: client.models.generate_content(
        model=MODEL, contents=prompt,
        config={"response_mime_type": "application/json", "response_schema": schema,
                "temperature": 0}))
    return json.loads(resp.text)

def generate_text(prompt: str) -> str:
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options={"api_version": "v1beta"})
    resp = _retry(lambda: client.models.generate_content(model=MODEL, contents=prompt,
                                          config={"temperature": 0.2}))
    return resp.text

def pdf_to_text(data: bytes) -> str:
    """Read a (scanned) PDF with Gemini. Used only when the PDF has no text layer."""
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options={"api_version": "v1beta"})
    resp = _retry(lambda: client.models.generate_content(model=MODEL, contents=[
        types.Part.from_bytes(data=data, mime_type="application/pdf"),
        "Transcribe this clinical note exactly as plain text. Do not summarise or add anything."],
        config={"temperature": 0}))
    return resp.text
