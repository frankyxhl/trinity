from __future__ import annotations

import os
import selectors
import subprocess
import sys
import time

from . import claude_code


def run_harness(
    argv,
    *,
    cwd,
    env,
    heartbeat,
    heartbeat_source,
    poll_s,
    time_s,
    on_line,
    stdin=subprocess.DEVNULL,
) -> dict:
    interval = claude_code._poll_interval(poll_s)
    started = time.monotonic()
    timeout_s = claude_code._finite_timeout(time_s)
    deadline = started + timeout_s if timeout_s is not None else None
    started_at = time.time()
    stdout_read, stdout_write = os.pipe()
    try:
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=stdin,
            stdout=stdout_write,
            stderr=subprocess.PIPE,
            bufsize=0,
            start_new_session=True,
        )
    except BaseException:
        os.close(stdout_read)
        os.close(stdout_write)
        raise
    os.close(stdout_write)

    output = bytearray()
    errors = bytearray()
    pending = bytearray()
    timed_out = False
    interrupted = False
    selector = None
    last_heartbeat = None

    def emit_line(raw: bytes) -> None:
        on_line(raw.decode("utf-8", errors="replace"))

    def emit_pending() -> None:
        if pending:
            emit_line(bytes(pending))
            del pending[:]

    def read_ready(events, *, emit_heartbeat=True):
        nonlocal last_heartbeat
        for key, _mask in events:
            descriptor = key.fd
            try:
                chunk = os.read(descriptor, 65536)
            except (BlockingIOError, InterruptedError):
                continue
            if not chunk:
                selector.unregister(descriptor)
                continue
            if key.data == "stdout":
                output.extend(chunk)
                pending.extend(chunk)
                while True:
                    index = pending.find(b"\n")
                    if index < 0:
                        break
                    emit_line(bytes(pending[:index]))
                    del pending[: index + 1]
                observed_at = time.monotonic()
                if emit_heartbeat and (
                    last_heartbeat is None or observed_at - last_heartbeat >= interval
                ):
                    heartbeat(heartbeat_source)
                    last_heartbeat = observed_at
            else:
                errors.extend(chunk)

    def drain_for(grace_s, *, emit_heartbeat=False):
        if selector is None:
            return
        drain_deadline = time.monotonic() + grace_s
        while selector.get_map():
            remaining = drain_deadline - time.monotonic()
            if remaining <= 0:
                break
            read_ready(selector.select(remaining), emit_heartbeat=emit_heartbeat)

    try:
        selector = selectors.DefaultSelector()
        stderr_fd = proc.stderr.fileno()
        os.set_blocking(stdout_read, False)
        os.set_blocking(stderr_fd, False)
        selector.register(stdout_read, selectors.EVENT_READ, "stdout")
        selector.register(stderr_fd, selectors.EVENT_READ, "stderr")
        while True:
            if proc.poll() is not None:
                drain_for(claude_code._DRAIN_GRACE_S)
                if selector.get_map():
                    claude_code._kill_group(proc.pid)
                break
            remaining = (
                deadline - time.monotonic() if deadline is not None else interval
            )
            if deadline is not None and remaining <= 0:
                timed_out = True
                claude_code._kill_group(proc.pid)
                break
            wait_s = min(interval, remaining) if deadline is not None else interval
            if not selector.get_map():
                wait_s = min(wait_s, 0.05)
            read_ready(selector.select(wait_s))
    except KeyboardInterrupt:
        interrupted = True
        claude_code._kill_group(proc.pid)
    except BaseException:
        claude_code._kill_group(proc.pid)
        raise
    finally:
        cleanup_failure = sys.exc_info()

        def attempt_cleanup(action, *, timeout_ok=False):
            nonlocal cleanup_failure
            try:
                action()
            except subprocess.TimeoutExpired:
                if not timeout_ok and cleanup_failure[0] is None:
                    cleanup_failure = sys.exc_info()
            except BaseException:
                if cleanup_failure[0] is None:
                    cleanup_failure = sys.exc_info()

        if timed_out or interrupted or cleanup_failure[0] is not None:
            grace = claude_code._DRAIN_GRACE_S
            attempt_cleanup(lambda: drain_for(grace))
            attempt_cleanup(lambda: proc.wait(timeout=grace), timeout_ok=True)
        if selector is not None:
            attempt_cleanup(selector.close)
        attempt_cleanup(lambda: os.close(stdout_read))
        if proc.stderr is not None:
            attempt_cleanup(proc.stderr.close)
        ended_at = time.time()
        if cleanup_failure[0] is not None:
            raise cleanup_failure[1].with_traceback(cleanup_failure[2])

    emit_pending()
    wall_s = int(time.monotonic() - started)
    return {
        "rc": proc.poll(),
        "stdout": output.decode("utf-8", errors="replace"),
        "stderr": errors.decode("utf-8", errors="replace"),
        "timed_out": timed_out,
        "interrupted": interrupted,
        "wall_s": wall_s,
        "started_at": started_at,
        "ended_at": ended_at,
    }
