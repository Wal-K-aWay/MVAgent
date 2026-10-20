"""Unified end-to-end benchmark harness around the vendored official evaluation code."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))
