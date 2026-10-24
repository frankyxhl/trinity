#!/usr/bin/env bash
# tests/test_agy_opus_wrapper.sh — behaviour tests for providers/bin/agy-opus
# (forge pilot/trinity#1: B1 shared-scratch race, F3 flag-scan vs task text,
# plus the pinned-model contract; review-judge verdict 2026-09-05, F2).
#
# Every scenario runs the wrapper under a fake HOME with doubles on PATH —
# `agy` (records every invocation and argv) and
# `pgrep` (reports whether another agy process is alive). Nothing touches the
# real ~/.gemini/antigravity-cli or the real CLI.
#
# Helper vocabulary (QA-0001 R9 — helpers may branch; scenarios may not):
#   given_fake_agy — install the fake `agy` that logs every call and records argv
#   given_quiet_pgrep    — install a fake `pgrep` reporting NO other agy alive
#   given_busy_pgrep     — install a fake `pgrep` reporting an agy process alive
#   given_stale_file     — drop stale.txt into the shared scratch dir
#   given_live_lock      — pre-create the run lock held by a live foreign process
#   given_dead_lock      — pre-create the run lock held by an exited process
#   given_fake_agy_no_usage — install the fake `agy` that logs every call and
#   answers a normal run like given_fake_agy
#   when_wrapper <args…> — run the wrapper; captures RC (exit) / OUT / ERR
#   assert_rc <n> <msg>          — exit status is exactly n
#   assert_err <text> <msg>      — stderr contains text
#   assert_argv <text> <msg>     — the fake agy received text in its argv
#   assert_no_argv <msg>         — the fake agy was never exec'd for a normal run
#   assert_no_usage_call <msg>   — the fake agy never received --print=/usage
#   assert_present / assert_absent <path> <msg> — file exists / does not

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WRAP="${REPO_DIR}/providers/bin/agy-opus"
ORIG_PATH="$PATH"

PASS=0
FAIL=0
T=""

pass() { PASS=$((PASS + 1)); echo "PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "FAIL: $1"; }

setup() {
    T=$(mktemp -d "${TMPDIR:-/tmp}/agywrap.XXXXXX")
    HOME_DIR="$T/home"
    mkdir -p "$HOME_DIR/.gemini/antigravity-cli/scratch"
    BIN="$T/bin"
    mkdir -p "$BIN"
    ARGV_LOG="$T/argv.log"
    : > "$ARGV_LOG"
    CALLS_LOG="$T/calls.log"
    : > "$CALLS_LOG"
    export PATH="$ORIG_PATH"
    export HOME="$HOME_DIR"
    export AGY_OPUS_LOCK_WAIT=2
    SCRATCH="$HOME_DIR/.gemini/antigravity-cli/scratch"
    LOCK_DIR="${SCRATCH}.lock"
    CLEANUP_PIDS=""
}

teardown() {
    [ -n "$CLEANUP_PIDS" ] && kill $CLEANUP_PIDS 2>/dev/null
    [ -n "$T" ] && rm -rf "$T"
}
trap teardown EXIT

given_fake_agy() {
    cat > "$BIN/agy" <<FAKE
#!/bin/sh
printf '%s\n' "\$*" >> '${CALLS_LOG}'
i=0
for a in "\$@"; do
    i=\$((i + 1))
    printf 'ARG%d=[%s]\n' "\$i" "\$a"
done > '${ARGV_LOG}'
printf '{"conversation_id":"c-1","status":"SUCCESS","response":"ok"}\n'
FAKE
    chmod +x "$BIN/agy"
    export PATH="$BIN:$ORIG_PATH"
}

given_fake_agy_no_usage() {
    cat > "$BIN/agy" <<FAKE
#!/bin/sh
printf '%s\n' "\$*" >> '${CALLS_LOG}'
for a in "\$@"; do
    case "\$a" in
        --print=/usage)
            exit 1 ;;
    esac
done
i=0
for a in "\$@"; do
    i=\$((i + 1))
    printf 'ARG%d=[%s]\n' "\$i" "\$a"
done > '${ARGV_LOG}'
printf '{"conversation_id":"c-1","status":"SUCCESS","response":"ok"}\n'
FAKE
    chmod +x "$BIN/agy"
    export PATH="$BIN:$ORIG_PATH"
}

given_quiet_pgrep() {
    printf '#!/bin/sh\nexit 1\n' > "$BIN/pgrep"
    chmod +x "$BIN/pgrep"
}

given_busy_pgrep() {
    printf '#!/bin/sh\nexit 0\n' > "$BIN/pgrep"
    chmod +x "$BIN/pgrep"
}

given_stale_file() {
    printf 'stale\n' > "$SCRATCH/stale.txt"
}

given_live_lock() {
    sleep 30 &
    LIVE_PID=$!
    disown "$LIVE_PID" 2>/dev/null || true
    CLEANUP_PIDS="$CLEANUP_PIDS $LIVE_PID"
    mkdir -p "$LOCK_DIR"
    printf '%s\n' "$LIVE_PID" > "$LOCK_DIR/pid"
}

given_dead_lock() {
    sh -c 'exit 0' &
    DEAD_PID=$!
    wait "$DEAD_PID"
    mkdir -p "$LOCK_DIR"
    printf '%s\n' "$DEAD_PID" > "$LOCK_DIR/pid"
}

when_wrapper() {
    OUT=$("$WRAP" "$@" 2>"$T/err")
    RC=$?
    ERR=$(cat "$T/err")
}

assert_rc() {
    if [ "$RC" -eq "$1" ]; then pass "$2"; else fail "$2: rc=$RC want $1"; fi
}

assert_err() {
    if printf '%s\n' "$ERR" | grep -qF -- "$1"; then pass "$2"; else fail "$2: stderr lacks [$1]"; fi
}

assert_argv() {
    if grep -qF -- "$1" "$ARGV_LOG"; then pass "$2"; else fail "$2: argv lacks [$1]"; fi
}

assert_no_argv() {
    if [ ! -s "$ARGV_LOG" ]; then pass "$1"; else fail "$1: agy was invoked ($(cat "$ARGV_LOG"))"; fi
}

assert_no_usage_call() {
    if ! grep -qF -- "--print=/usage" "$CALLS_LOG"; then pass "$1"; else fail "$1: agy received --print=/usage"; fi
}

assert_present() {
    if [ -e "$1" ]; then pass "$2"; else fail "$2: $1 missing"; fi
}

assert_absent() {
    if [ ! -e "$1" ]; then pass "$2"; else fail "$2: $1 still exists"; fi
}

run_scenario() {
    setup
    "$1"
    teardown
    T=""
}

t_pins_model() {
    given_fake_agy
    given_quiet_pgrep

    when_wrapper "hello"

    assert_rc 0 "wrapper starts and execs agy"
    assert_argv "claude-opus-5-5-high" "model is pinned to claude-opus-5-5-high"
    assert_argv "[15m]" "print timeout defaults to 15m"
}

t_task_text_preserved_verbatim() {
    given_fake_agy
    given_quiet_pgrep

    when_wrapper "say 'hi' \$HOME & done"

    assert_rc 0 "task with quotes, dollar and ampersand is accepted"
    assert_argv "--print=say 'hi' \$HOME & done" "task text reaches agy verbatim"
}

t_caller_flags_survive_quoting() {
    given_fake_agy
    given_quiet_pgrep

    when_wrapper --add-dir "/tmp/my proj" --conversation c-9 "task"

    assert_rc 0 "flags with spaces are accepted"
    assert_argv "/tmp/my proj" "--add-dir value with a space survives"
    assert_argv "c-9" "--conversation value survives"
}

t_refuses_model_override_without_exec() {
    given_fake_agy
    given_quiet_pgrep

    when_wrapper --model gemini-3.8-flash "hello"

    assert_rc 2 "--model override is refused with exit 2"
    assert_err "pinned" "refusal says the model is pinned"
    assert_no_argv "agy is never invoked after the refusal"
}

t_task_dash_p_is_still_the_task() {
    given_fake_agy
    given_quiet_pgrep

    when_wrapper "-p"

    assert_rc 0 "a lone task text of -p is accepted as the task"
    assert_argv "--print=-p" "-p reaches agy as the print task, not a flag"
}

t_task_model_prefix_is_still_the_task() {
    given_fake_agy
    given_quiet_pgrep

    when_wrapper "--model=evil task"

    assert_rc 0 "a task text starting with --model= is accepted as the task"
    assert_argv "--print=--model=evil task" "the whole text reaches agy as the print task"
}

t_clears_stale_scratch_on_solo_run() {
    given_fake_agy
    given_quiet_pgrep
    given_stale_file

    when_wrapper "hello"

    assert_rc 0 "solo run proceeds"
    assert_absent "$SCRATCH/stale.txt" "stale scratch file is cleared before a solo run"
}

t_skips_clear_while_agy_alive() {
    given_fake_agy
    given_busy_pgrep
    given_stale_file

    when_wrapper "hello"

    assert_rc 0 "run proceeds while another agy is alive"
    assert_present "$SCRATCH/stale.txt" "scratch clear is skipped while another agy is alive"
}

t_refuses_while_lock_held() {
    given_fake_agy
    given_quiet_pgrep
    given_live_lock

    when_wrapper "hello"

    assert_rc 1 "second run refuses while the lock is held"
    assert_err "another agy-opus run" "refusal names the active run lock"
    assert_no_argv "agy is never invoked while locked"
}

t_takes_over_dead_holder_lock() {
    given_fake_agy
    given_quiet_pgrep
    given_dead_lock

    when_wrapper "hello"

    assert_rc 0 "stale lock of a dead holder is taken over"
    assert_argv "--print=hello" "run proceeds after taking over the stale lock"
}

t_finished_run_does_not_block_the_next() {
    given_fake_agy
    given_quiet_pgrep

    when_wrapper "first run"
    assert_rc 0 "first run succeeds"

    when_wrapper "second run"
    assert_rc 0 "a finished run's lock does not block the next run"
}

t_no_arguments_is_a_usage_error() {
    given_fake_agy
    given_quiet_pgrep

    when_wrapper

    assert_rc 2 "no arguments is a usage error"
    assert_err "usage:" "usage message is printed"
    assert_no_argv "agy is never invoked"
}

t_runs_without_usage_read() {
    given_fake_agy
    given_quiet_pgrep

    when_wrapper "hello"

    assert_rc 0 "wrapper runs without reading /usage"
    assert_no_usage_call "wrapper does not read /usage"
    assert_argv "hello" "task reaches agy without a usage read"
    assert_argv "claude-opus-5-5-high" "model pin claude-opus-5-5-high survives without a usage read"
}

t_runs_when_usage_unreadable() {
    given_fake_agy_no_usage
    given_quiet_pgrep

    when_wrapper "hello"

    assert_rc 0 "wrapper runs when /usage is unreadable"
    assert_argv "hello" "run reaches agy when /usage is unreadable"
}

run_scenario t_pins_model
run_scenario t_task_text_preserved_verbatim
run_scenario t_caller_flags_survive_quoting
run_scenario t_refuses_model_override_without_exec
run_scenario t_task_dash_p_is_still_the_task
run_scenario t_task_model_prefix_is_still_the_task
run_scenario t_clears_stale_scratch_on_solo_run
run_scenario t_skips_clear_while_agy_alive
run_scenario t_refuses_while_lock_held
run_scenario t_takes_over_dead_holder_lock
run_scenario t_finished_run_does_not_block_the_next
run_scenario t_no_arguments_is_a_usage_error
run_scenario t_runs_without_usage_read
run_scenario t_runs_when_usage_unreadable

echo "agy-opus wrapper: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
