#!/usr/bin/env bash
# TRN-2018 M1 test fixture: sleeps far longer than test timeout.
# Used to exercise the timeout path (returncode 124 + TERM/KILL escalation).
echo "starting hang"
sleep 999
exit 0
