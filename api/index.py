import pathlib, sys, os

# ── Vercel Lambda path setup ───────────────────────────────────────────────
# api/index.py lives at  <root>/api/index.py  →  parent.parent = <root>/
_root = pathlib.Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
os.environ["FOLLOWSAFE_ROOT"] = str(_root)

from followsafe.api import app  # noqa: E402

# Mangum wraps the FastAPI ASGI app for AWS Lambda / Vercel.
# Without it, Vercel rewrites the path (e.g. /api/run → /api/index) and
# FastAPI sees "/api/index" instead of the real route → every request 404s.
from mangum import Mangum  # noqa: E402

handler = Mangum(app, lifespan="off")
