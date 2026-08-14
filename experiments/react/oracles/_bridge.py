"""Read-only import bridge to experiments/reflexion (spec: reuse, never copy).

Appends (never inserts) so react's own modules shadow same-named reflexion
modules when running from experiments/react.
"""
import pathlib
import sys

_REFLEXION_DIR = str(pathlib.Path(__file__).resolve().parents[2] / "reflexion")
if _REFLEXION_DIR not in sys.path:
    sys.path.append(_REFLEXION_DIR)

import validator  # noqa: E402  (experiments/reflexion/validator.py)
