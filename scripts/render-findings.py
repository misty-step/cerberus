#!/usr/bin/env python3

"""Render findings markdown from a verdict JSON file."""

import sys

from lib.render_findings import main


if __name__ == "__main__":
    sys.exit(main())
