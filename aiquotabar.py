#!/usr/bin/env python3
"""AIQuotaBar -- backwards-compatible entry point.

The real code lives in the aiquotabar/ package.
This shim keeps `python3 aiquotabar.py` working for
install.sh and the LaunchAgent.
"""
from aiquotabar.__main__ import main

if __name__ == "__main__":
    main()
