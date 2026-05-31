"""Provider runtime and dispatch helpers for Trinity reviews."""

import concurrent.futures
import datetime as dt
import errno
import fnmatch
import os
import pty
import shlex
import signal
import subprocess
import sys
import threading
import time
import tty

try:
    from . import provider_state as _rm
except ImportError:
    import provider_state as _rm


PROCESS_GROUP_KILL_GRACE_SECONDS = 5
_STDERR_SENTINEL = "\n%%TRINITY-RAW-STDERR-BOUNDARY-9c3d2a1f7e%%\n"


def parse_provider_command(provider, provider_config):
    if not isinstance(provider_config, dict):
        raise ValueError("provider config must be an object")
    cli = provider_config.get("cli")
    if not isinstance(cli, str) or not cli.strip():
        raise ValueError("missing cli")
    expanded = os.path.expandvars(os.path.expanduser(cli))
    try:
        command = shlex.split(expanded)
    except ValueError as exc:
        raise ValueError(f"invalid cli: {exc}") from exc
    if not command:
        raise ValueError("missing cli")
    return command


def provider_timeout(provider, provider_config):
    raw_timeout = provider_config.get("timeout", 360)
    if isinstance(raw_timeout, bool):
        raise ValueError(f"invalid timeout: {raw_timeout}")
    try:
        timeout = int(raw_timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid timeout: {raw_timeout}") from exc
    if timeout <= 0:
        raise ValueError(f"invalid timeout: {raw_timeout}")
    return timeout


def command_has_path(command):
    return os.path.sep in command or (
        os.path.altsep is not None and os.path.altsep in command
    )


def provider_command(provider, provider_config):
    try:
        return parse_provider_command(provider, provider_config)
    except ValueError as exc:
        raise SystemExit(f"trinity-codex: provider {provider} {exc}") from exc


def build_prompt_handoff(prompt_path):
    return (
        "Read the complete Trinity review prompt from the file below, then perform "
        "the requested code review.\n\n"
        f"Prompt file: {prompt_path}"
    )


def progress(message):
    print(f"trinity: {message}", file=sys.stderr, flush=True)


def timestamp():
    return dt.datetime.now().isoformat(timespec="seconds")


def elapsed_seconds(started):
    return max(0, int(time.monotonic() - started))


class ActiveProcessRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._items = {}
        self._started = set()

    def add(self, provider, popen, started_at):
        with self._lock:
            self._started.add(provider)
            self._items[provider] = {
                "provider": provider,
                "pid": popen.pid,
                "popen": popen,
                "started_at": started_at,
            }

    def remove(self, provider, popen):
        with self._lock:
            current = self._items.get(provider)
            if current is not None and current["popen"] is popen:
                self._items.pop(provider, None)

    def snapshot(self):
        with self._lock:
            return list(self._items.values())

    def started_providers(self):
        with self._lock:
            return set(self._started)


class ReviewInterrupted(Exception):
    def __init__(self, cleanup, started_providers):
        super().__init__("review interrupted")
        self.cleanup = cleanup
        self.started_providers = started_providers


class ReviewOrchestrationError(Exception):
    def __init__(self, message, cleanup, started_providers):
        super().__init__(message)
        self.cleanup = cleanup
        self.started_providers = started_providers


def process_group_id(popen):
    try:
        return os.getpgid(popen.pid)
    except ProcessLookupError:
        return None
    except PermissionError:
        return "permission_denied"


def signal_process_group(popen, sig):
    pgid = process_group_id(popen)
    if pgid is None:
        return "already_exited"
    if pgid == "permission_denied":
        return pgid
    try:
        os.killpg(pgid, sig)
        return "signaled"
    except ProcessLookupError:
        return "already_exited"
    except PermissionError:
        return "permission_denied"


def terminate_process_group(popen, grace_seconds=PROCESS_GROUP_KILL_GRACE_SECONDS):
    if popen.poll() is not None:
        return "already_exited"
    term_status = signal_process_group(popen, signal.SIGTERM)
    if term_status == "already_exited":
        return term_status
    if term_status != "signaled":
        return term_status
    try:
        popen.wait(timeout=grace_seconds)
        return "terminated"
    except subprocess.TimeoutExpired:
        kill_status = signal_process_group(popen, signal.SIGKILL)
        if kill_status == "already_exited":
            return kill_status
        if kill_status != "signaled":
            return kill_status
        try:
            popen.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            return "kill_timeout"
        return "killed"


def cleanup_active_processes(registry):
    cleanup = {}
    for item in registry.snapshot():
        cleanup[item["provider"]] = {
            "pid": item["pid"],
            "result": terminate_process_group(item["popen"]),
        }
    return cleanup


def raw_output(stdout, stderr):
    # TRN-3022 coupling: the _STDERR_SENTINEL written here is consumed by
    # _strip_stderr_region — do NOT change the sentinel format without
    # updating both. The sentinel is a unique marker (random hex tag) so
    # neither stdout nor stderr can plausibly contain a colliding string.
    # Always append the sentinel (even with empty stderr) so the boundary
    # exists unambiguously.
    return (stdout or "") + _STDERR_SENTINEL + (stderr or "")


def write_text_atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        temp_path.write_text(text, encoding="utf-8")
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def timeout_partial_output(exc, stdout=None, stderr=None):
    def normalize(value):
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value

    return raw_output(
        normalize(stdout) or normalize(exc.stdout),
        normalize(stderr) or normalize(exc.stderr),
    )


def _set_raw_pty(fd):
    """Disable PTY newline translation while keeping child stdout as a TTY."""
    try:
        tty.setraw(fd)
    except OSError:
        pass


def _copy_pty_to_file(master_fd, output_path, errors):
    try:
        with open(output_path, "ab", buffering=0) as out:
            while True:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError as exc:
                    if exc.errno == errno.EIO:
                        break
                    raise
                if not chunk:
                    break
                out.write(chunk)
    except Exception as exc:
        errors.append(exc)
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass


_UNIVERSAL_ENV_KEEP_LITERAL = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "LANG",
        "TERM",
        "SHELL",
        "TZ",
        "TMPDIR",
        "XDG_RUNTIME_DIR",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "XDG_DATA_HOME",
        "SSH_AUTH_SOCK",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "PWD",
    }
)
_UNIVERSAL_ENV_KEEP_GLOB = ("LC_*", "GIT_*")
_DEFAULT_ENV_CLEAR_PATTERNS = (
    "*_BASE_URL",
    "*_API_BASE",
    "*_API_HOST",
    "OTEL_*",
    "TRINITY_DISABLE_DISPATCH",
    "TRINITY_MCP_TOKEN",
)


def _matches_any(key, patterns):
    return any(fnmatch.fnmatchcase(key, pat) for pat in patterns)


def _is_essential(key):
    if key in _UNIVERSAL_ENV_KEEP_LITERAL:
        return True
    return _matches_any(key, _UNIVERSAL_ENV_KEEP_GLOB)


def build_provider_env(base_env=None):
    """Build a sanitized env dict for spawning provider CLIs (TRN-3023).

    Strips known-problematic patterns (vendor *_BASE_URL overrides, OTEL_*
    telemetry leakage, Trinity control vars from caller's shell).
    Preserves universal essentials regardless of clear patterns. Returns
    a fresh dict suitable for `subprocess.Popen(env=...)`.

    Universal essentials are checked BEFORE the clearlist, so a future
    clearlist pattern that happened to match an essential (e.g., a
    pattern accidentally globbing PATH) would still preserve the
    essential.

    `base_env=None` resolves to `os.environ` at call time (avoids the
    mutable-default antipattern if `os.environ` mutates between calls).

    Patterns use `fnmatch.fnmatchcase` (case-sensitive — POSIX env
    names ARE case-sensitive even on macOS/Windows).
    """
    if base_env is None:
        base_env = os.environ
    sanitized = {}
    for key, value in base_env.items():
        if _is_essential(key):
            sanitized[key] = value
            continue
        if _matches_any(key, _DEFAULT_ENV_CLEAR_PATTERNS):
            continue
        sanitized[key] = value
    return sanitized


def run_provider(
    provider,
    provider_config,
    prompt_path,
    review_dir,
    root,
    registry,
):
    # TRN-2018 M1: stdout streams through a PTY into logs/<p>.stdout.log so
    # child processes that line-buffer on isatty() emit live output instead of
    # block-buffering until exit. stderr still streams to its own log file.
    # raw/<p>.txt is composed from closed logs for backward compatibility.
    raw_path = review_dir / "raw" / f"{provider}.txt"
    # Defensive: production cmd_review path creates logs/ via make_review_dir,
    # but unit tests that build review_dir manually may skip it.
    (review_dir / "logs").mkdir(exist_ok=True)
    stdout_path = review_dir / "logs" / f"{provider}.stdout.log"
    stderr_path = review_dir / "logs" / f"{provider}.stderr.log"
    cmd = provider_command(provider, provider_config) + [
        build_prompt_handoff(prompt_path)
    ]
    provider_env = build_provider_env()
    try:
        timeout = provider_timeout(provider, provider_config)
    except ValueError as exc:
        raise SystemExit(f"trinity-codex: provider {provider} {exc}") from exc
    started = timestamp()
    started_monotonic = time.monotonic()
    progress(f"starting provider {provider} timeout={timeout}s")
    popen = None
    outcome = None  # tuple describing terminal state; consumed below for raw compose
    stdout_path.write_bytes(b"")
    stdout_master_fd = None
    stdout_slave_fd = None
    stdout_thread = None
    stdout_reader_errors = []
    try:
        stdout_master_fd, stdout_slave_fd = pty.openpty()
        _set_raw_pty(stdout_slave_fd)
    except OSError as exc:
        raise RuntimeError(f"failed to create PTY for provider stdout: {exc}") from exc
    stdout_thread = threading.Thread(
        target=_copy_pty_to_file,
        args=(stdout_master_fd, stdout_path, stdout_reader_errors),
        daemon=True,
    )
    stdout_thread.start()
    stdout_master_fd = None
    with open(stderr_path, "w", buffering=1, encoding="utf-8") as ferr:
        try:
            popen = subprocess.Popen(
                cmd,
                cwd=str(root),
                stdout=stdout_slave_fd,
                stderr=ferr,
                text=True,
                start_new_session=True,
                env=provider_env,
            )
            os.close(stdout_slave_fd)
            stdout_slave_fd = None
            registry.add(provider, popen, started)
            _rm.update_provider_state(
                review_dir,
                provider,
                status="running",
                pid=getattr(popen, "pid", None),
                started_at=started,
                stdout_path=str(stdout_path.relative_to(review_dir)),
                stderr_path=str(stderr_path.relative_to(review_dir)),
            )
            popen.wait(timeout=timeout)
            finished = timestamp()
            # TRN-2018 M1: derive terminal state from returncode. A clean
            # exit with rc != 0 is `failed`, not `finished`. finalize_metadata's
            # top-level status precedence (failed > timed_out > finished)
            # then correctly surfaces `failed` for any provider with non-zero rc.
            terminal_state = "finished" if popen.returncode == 0 else "failed"
            progress(
                f"provider {provider} {terminal_state} returncode={popen.returncode} "
                f"elapsed={elapsed_seconds(started_monotonic)}s"
            )
            _rm.update_provider_state(
                review_dir,
                provider,
                status=terminal_state,
                returncode=popen.returncode,
                finished_at=finished,
            )
            outcome = ("finished", popen.returncode, finished)
        except FileNotFoundError as exc:
            finished = timestamp()
            progress(
                f"provider {provider} failed returncode=127 "
                f"elapsed={elapsed_seconds(started_monotonic)}s"
            )
            _rm.update_provider_state(
                review_dir,
                provider,
                status="failed",
                returncode=127,
                finished_at=finished,
            )
            outcome = ("filenotfound", str(exc), finished)
        except subprocess.TimeoutExpired as exc:
            cleanup_result = terminate_process_group(popen)
            # Best effort: wait briefly so the child fully exits before we
            # close its stdout/stderr file handles.
            try:
                popen.wait(timeout=1)
            except (subprocess.TimeoutExpired, ValueError):
                pass
            finished = timestamp()
            progress(
                f"provider {provider} timed out returncode=124 "
                f"cleanup={cleanup_result} elapsed={elapsed_seconds(started_monotonic)}s"
            )
            _rm.update_provider_state(
                review_dir,
                provider,
                status="timed_out",
                returncode=124,
                finished_at=finished,
            )
            outcome = ("timeout", exc, timeout, finished)
        except Exception:
            if popen is not None and popen.poll() is None:
                terminate_process_group(popen)
            raise
        finally:
            try:
                ferr.flush()
            except Exception:
                pass
            if stdout_slave_fd is not None:
                try:
                    os.close(stdout_slave_fd)
                except OSError:
                    pass
            if stdout_master_fd is not None:
                try:
                    os.close(stdout_master_fd)
                except OSError:
                    pass
            if stdout_thread is not None:
                stdout_thread.join()
            if popen is not None:
                registry.remove(provider, popen)
    if stdout_reader_errors:
        raise RuntimeError(
            f"provider {provider} stdout reader failed: {stdout_reader_errors[0]}"
        )

    # Log file handles are now closed; compose raw_path from disk content.
    # TRN-2018 R3 fix (codex R2 P2): append the result entry to metadata
    # immediately so status readers can discover completed providers'
    # artifacts before the full review finishes (parallel-provider case).
    # finalize_metadata later overwrites results with the canonical
    # ordered list from run_providers, so duplicate appends are harmless.
    if outcome[0] == "finished":
        _, rc, finished = outcome
        stdout_text = (
            stdout_path.read_text(errors="replace") if stdout_path.exists() else ""
        )
        stderr_text = (
            stderr_path.read_text(errors="replace") if stderr_path.exists() else ""
        )
        write_text_atomic(raw_path, raw_output(stdout_text, stderr_text))
        result = {
            "provider": provider,
            "returncode": rc,
            "raw": str(raw_path.relative_to(review_dir)),
            "started_at": started,
            "finished_at": finished,
        }
        _rm.append_result(review_dir, result)
        return result
    if outcome[0] == "filenotfound":
        _, msg, finished = outcome
        write_text_atomic(raw_path, f"ERROR: command not found: {msg}\n")
        result = {
            "provider": provider,
            "returncode": 127,
            "raw": str(raw_path.relative_to(review_dir)),
            "started_at": started,
            "finished_at": finished,
        }
        _rm.append_result(review_dir, result)
        return result
    # timeout
    _, exc, timeout_val, finished = outcome
    stdout_text = (
        stdout_path.read_text(errors="replace") if stdout_path.exists() else ""
    )
    stderr_text = (
        stderr_path.read_text(errors="replace") if stderr_path.exists() else ""
    )
    partial = timeout_partial_output(exc, stdout_text, stderr_text)
    output = f"ERROR: timeout after {timeout_val}s\n{exc}\n"
    if partial:
        output += "\n[partial output]\n" + partial
    write_text_atomic(raw_path, output)
    result = {
        "provider": provider,
        "returncode": 124,
        "raw": str(raw_path.relative_to(review_dir)),
        "started_at": started,
        "finished_at": finished,
    }
    _rm.append_result(review_dir, result)
    return result


def run_providers(
    max_workers,
    providers,
    provider_configs,
    prompt_path,
    review_dir,
    root,
    *,
    run_provider_fn=run_provider,
):
    registry = ActiveProcessRegistry()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    provider_iter = iter(providers)
    futures = {}
    results = {}

    def submit_provider(provider):
        future = executor.submit(
            run_provider_fn,
            provider,
            provider_configs[provider],
            prompt_path,
            review_dir,
            root,
            registry,
        )
        futures[future] = provider

    try:
        for provider in provider_iter:
            submit_provider(provider)
            if len(futures) >= max_workers:
                break
        while futures:
            done, _ = concurrent.futures.wait(
                futures, return_when=concurrent.futures.FIRST_COMPLETED
            )
            for future in done:
                provider = futures.pop(future)
                results[provider] = future.result()
                try:
                    submit_provider(next(provider_iter))
                except StopIteration:
                    pass
    except KeyboardInterrupt as exc:
        for future in futures:
            future.cancel()
        started_providers = registry.started_providers()
        cleanup = cleanup_active_processes(registry)
        executor.shutdown(wait=False)
        raise ReviewInterrupted(cleanup, started_providers) from exc
    except Exception as exc:
        for future in futures:
            future.cancel()
        started_providers = registry.started_providers()
        cleanup = cleanup_active_processes(registry)
        executor.shutdown(wait=False)
        raise ReviewOrchestrationError(str(exc), cleanup, started_providers) from exc
    else:
        executor.shutdown(wait=True)
    return [results[provider] for provider in providers]
