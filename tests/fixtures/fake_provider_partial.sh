#!/usr/bin/env bash
# TRN-2018 M1 test fixture: emits partial stdout, then sleeps for ~1s.
# Used to prove logs/<p>.stdout.log exists while provider is still running.
echo "partial output line 1"
sleep 1
echo "partial output line 2"
exit 0
