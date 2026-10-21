#!/usr/bin/env python3
"""Compatibility shim: the client is now athena.py (removed in a future release)."""
import os
import runpy
import sys

runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "athena.py"), run_name="__main__")
