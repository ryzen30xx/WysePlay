#!/usr/bin/env python3
"""
WysePlay — Main Entry Point
Unifies all components of the system.
Run directly with: python3 main.py [run|status|install|uninstall|stop]
"""

import sys, os

# Ensure src/ is on Python path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from unified_orchestrator import main

if __name__ == "__main__":
    main()
