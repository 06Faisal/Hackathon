"""OCR / ingestion: text files pass through; PDFs use pdftotext, scanned PDFs pytesseract."""
import subprocess, pathlib

def load_note(path: str) -> str:
    p = pathlib.Path(path)
    if p.suffix.lower() == ".pdf":
        txt = subprocess.run(["pdftotext", "-layout", str(p), "-"], capture_output=True, text=True).stdout
        if txt.strip():
            return txt
        import pytesseract
        from pdf2image import convert_from_path
        return "\n".join(pytesseract.image_to_string(img) for img in convert_from_path(str(p)))
    return p.read_text(encoding="utf-8")
