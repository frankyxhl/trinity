#!/usr/bin/env python3
"""Emit newline-terminated stdout without explicit flush, then sleep."""

import sys
import time

sys.stdout.write("buffered output before sleep\n")
time.sleep(1)
sys.stdout.write("buffered output after sleep\n")
