"""Pytest configuration for hierarchical experiment tests."""
import sys
import pathlib

# Add parent (hierarchical/) to sys.path so tests can import sibling modules
_hierarchical_dir = pathlib.Path(__file__).resolve().parent.parent
if str(_hierarchical_dir) not in sys.path:
    sys.path.insert(0, str(_hierarchical_dir))
