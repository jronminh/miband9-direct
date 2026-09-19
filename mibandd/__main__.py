#!/usr/bin/env python3
"""Entry point: `python -m mibandd`."""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from mibandd.main import main

if __name__ == "__main__":
    sys.exit(main())
