import pathlib, sys, os

# ── Vercel Lambda path setup ───────────────────────────────────────────────
# api/index.py lives at  <root>/api/index.py
# So parent = <root>/api/, parent.parent = <root>/
_root = pathlib.Path(__file__).resolve().parent.parent
# Make sure the project root is importable
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
# Tell followsafe.api where to find static/ and data/
os.environ["FOLLOWSAFE_ROOT"] = str(_root)

from followsafe.api import app  # noqa: E402  (must come after path setup)
