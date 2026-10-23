#!/usr/bin/env python3
"""Run skill evolution through the official evaluation adapter."""
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[1] / 'src')]
from eval.skill_eval.run import main

if __name__ == '__main__':
    main()
