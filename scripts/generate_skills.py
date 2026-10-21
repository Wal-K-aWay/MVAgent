#!/usr/bin/env python3
"""Generate a one-shot GLM skill bank without benchmark examples or feedback."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from skill_evolution.generation.cli import main

if __name__ == "__main__":
    main()
