#!/usr/bin/env python3
"""Location-independent Grok Bot MCP stdio launcher for desktop AI clients.

Does not accept key material or webhook tokens on the command line.
Installable command is also available as grokbot-mcp-stdio.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.stdio import main  # noqa: E402

if __name__ == "__main__":
    main()
