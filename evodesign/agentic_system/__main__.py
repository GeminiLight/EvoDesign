#!/usr/bin/env python3
"""
Entry point for running Text2Diagram workflow.

Usage:
    python -m evodesign.agentic_system --example 1
    python -m evodesign.agentic_system --start 1 --end 10
"""
import sys

from .main import main

if __name__ == "__main__":
    sys.exit(main())
