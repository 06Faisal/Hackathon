"""OCR / ingestion: text files pass through; PDFs use pypdf (text layer), then pdftotext,
then Gemini (scanned PDFs, when GEMINI_API_KEY is set), then local tesseract if installed."""
import io, subprocess, pathlib

def pdf_bytes_to_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
        txt = "\n".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(data)).pages)
        if txt.strip(): return txt
    except Exception:
        pass
    try:
        txt = subprocess.run(["pdftotext", "-layout", "-", "-"], input=data, capture_output=True).stdout.decode("utf-8", "ignore")
        if txt.strip(): return txt
    except Exception:
        pass
    from .. import llm
    if llm.available():
        return llm.pdf_to_text(data)
    try:
        import pytesseract
        from pdf2image import convert_from_bytes
        return "\n".join(pytesseract.image_to_string(img) for img in convert_from_bytes(data))
    except Exception:
        raise ValueError("This PDF is scanned (no text layer). Add GEMINI_API_KEY to read scanned PDFs, or paste the note text.")

def load_note(path: str) -> str:
    p = pathlib.Path(path)
    if p.suffix.lower() == ".pdf":
        return pdf_bytes_to_text(p.read_bytes())
    return p.read_text(encoding="utf-8")
