import pathlib, sys, os
_root = pathlib.Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
os.environ["FOLLOWSAFE_ROOT"] = str(_root)
from followsafe.api import app  # noqa: E402  (Vercel serves the ASGI `app` natively)
