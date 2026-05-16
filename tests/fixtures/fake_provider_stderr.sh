#!/usr/bin/env bash
# TRN-2018 M1 test fixture: emits to both stdout and stderr.
# Used to verify raw/<p>.txt format preservation (stdout, then
# `\n[stderr]\n` and stderr, per existing raw_output() helper).
echo "stdout line"
echo "stderr line" >&2
exit 0
