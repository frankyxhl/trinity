#!/usr/bin/env bash
# TRN-2018 M1 test fixture: emits to stderr then exits with rc=2.
# Used to verify provider_states.<p>.status == 'failed' (not 'finished')
# when a provider exits cleanly with a non-zero returncode.
echo "stdout before failure"
echo "explanatory error message" >&2
exit 2
