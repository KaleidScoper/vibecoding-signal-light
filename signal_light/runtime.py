"""Runtime process management for persistent signal-light states."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from signal_light.agent_signals import AgentSignal, SIGNALS
from signal_light.hardware import LightMapping, SignalLight, SignalLightError


STATE_DIR = Path(os.environ.get("SIGNAL_LIGHT_STATE_DIR", "/private/tmp/signal-light"))
PID_FILE = STATE_DIR / "worker.json"
LOG_FILE = STATE_DIR / "worker.log"
SESSION_FILE = STATE_DIR / "sessions.json"
LOCK_FILE = STATE_DIR / "state.lock"
SESSION_TTL_SECONDS = int(os.environ.get("SIGNAL_LIGHT_SESSION_TTL_SECONDS", "86400"))

RED_SIGNALS = {"permission", "blocked"}
YELLOW_SIGNALS = {"attention", "done"}
WORKING_SIGNALS = {"thinking", "working", "tool_done"}
SESSION_END_SIGNALS = {"session_end", "off"}
TURN_END_SIGNALS = {"turn_end"}


def apply_signal(signal: AgentSignal, *, speed: float = 1.0) -> None:
    """Apply a signal as the current persistent status."""
    if signal.repeat:
        if _worker_matches(signal.name):
            return
        stop_worker()
        start_worker(signal.name, speed=speed)
        return

    stop_worker()
    _play_with_retries(signal, speed=speed)


def apply_session_signal(session_key: str, signal_name: str, *, speed: float = 1.0) -> str:
    """Update one Codex session state, then apply the aggregated global state."""
    with _state_lock():
        state = _read_session_state()
        sessions = state.setdefault("sessions", {})
        now = time.time()
        _prune_sessions(sessions, now)

        if signal_name in SESSION_END_SIGNALS:
            sessions.pop(session_key, None)
        elif signal_name in TURN_END_SIGNALS:
            current = sessions.get(session_key)
            current_signal = current.get("signal") if isinstance(current, dict) else None
            if current_signal not in RED_SIGNALS:
                sessions.pop(session_key, None)
        else:
            sessions[session_key] = {
                "signal": signal_name,
                "updated_at": now,
            }

        aggregate = aggregate_sessions(sessions)
        _write_session_state(state)
        apply_signal(SIGNALS[aggregate], speed=speed)
        return aggregate


def clear_session_state() -> None:
    """Clear all tracked Codex session states."""
    with _state_lock():
        _write_session_state({"sessions": {}})


def aggregate_sessions(sessions: dict[str, object]) -> str:
    signals = []
    for value in sessions.values():
        if isinstance(value, dict):
            signal_name = value.get("signal")
            if isinstance(signal_name, str):
                signals.append(signal_name)

    if any(signal_name in RED_SIGNALS for signal_name in signals):
        return "permission"
    if any(signal_name in YELLOW_SIGNALS for signal_name in signals):
        return "attention"
    if any(signal_name in WORKING_SIGNALS for signal_name in signals):
        return "working"
    return "idle"


def read_session_snapshot() -> dict[str, object]:
    state = _read_session_state()
    sessions = state.get("sessions", {})
    if not isinstance(sessions, dict):
        sessions = {}
    now = time.time()
    _prune_sessions(sessions, now)
    aggregate = aggregate_sessions(sessions)
    return {
        "aggregate": aggregate,
        "sessions": sessions,
    }


def run_worker(signal_name: str, *, speed: float = 1.0) -> int:
    signal_to_run = SIGNALS[signal_name]
    if not signal_to_run.repeat:
        raise SignalLightError(f"Signal {signal_name} is not a repeating signal.")

    with SignalLight(LightMapping.from_env(os.environ)) as light:
        signal_to_run.play_forever(light, speed=speed)
    return 0


@contextmanager
def _state_lock() -> Iterator[None]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+") as lock_file:
        try:
            import fcntl

            fcntl.flock(lock_file, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_UN)
            except Exception:
                pass


def _read_session_state() -> dict[str, object]:
    try:
        state = json.loads(SESSION_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"sessions": {}}

    if not isinstance(state, dict):
        return {"sessions": {}}
    if not isinstance(state.get("sessions"), dict):
        state["sessions"] = {}
    return state


def _write_session_state(state: dict[str, object]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def _prune_sessions(sessions: dict[str, object], now: float) -> None:
    expired = []
    for session_key, value in sessions.items():
        if not isinstance(value, dict):
            expired.append(session_key)
            continue
        updated_at = value.get("updated_at")
        if not isinstance(updated_at, (int, float)) or now - updated_at > SESSION_TTL_SECONDS:
            expired.append(session_key)

    for session_key in expired:
        sessions.pop(session_key, None)


def start_worker(signal_name: str, *, speed: float = 1.0) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "signal_light",
        "worker",
        signal_name,
        "--speed",
        str(speed),
    ]
    log = LOG_FILE.open("ab")
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            cwd=Path(__file__).resolve().parents[1],
            env=os.environ.copy(),
            start_new_session=True,
        )
    finally:
        log.close()

    time.sleep(0.2)
    if process.poll() is not None:
        raise SignalLightError(_worker_error_message(signal_name))

    PID_FILE.write_text(
        json.dumps(
            {
                "pid": process.pid,
                "signal": signal_name,
                "started_at": time.time(),
            },
            ensure_ascii=False,
        )
    )


def _worker_matches(signal_name: str) -> bool:
    state = _read_worker_state()
    pid = state.get("pid")
    return state.get("signal") == signal_name and isinstance(pid, int) and _is_running(pid)


def _play_with_retries(signal: AgentSignal, *, speed: float) -> None:
    last_error: SignalLightError | None = None
    for _ in range(12):
        try:
            with SignalLight(LightMapping.from_env(os.environ)) as light:
                signal.play(light, speed=speed)
            return
        except SignalLightError as exc:
            last_error = exc
            time.sleep(0.15)

    raise last_error or SignalLightError("Failed to apply signal state.")


def _worker_error_message(signal_name: str) -> str:
    detail = ""
    try:
        detail = LOG_FILE.read_text(errors="replace").strip().splitlines()[-1]
    except (FileNotFoundError, IndexError):
        pass

    if detail:
        return f"Signal worker for {signal_name} exited immediately: {detail}"
    return f"Signal worker for {signal_name} exited immediately."


def stop_worker() -> None:
    state = _read_worker_state()
    pid = state.get("pid")
    if isinstance(pid, int) and pid > 0 and pid != os.getpid():
        _terminate(pid)

    try:
        PID_FILE.unlink()
    except FileNotFoundError:
        pass


def _read_worker_state() -> dict[str, object]:
    try:
        return json.loads(PID_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _terminate(pid: int) -> None:
    if not _is_running(pid):
        return

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError as exc:
        raise SignalLightError(f"Cannot stop existing signal worker {pid}: {exc}") from exc

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if not _is_running(pid):
            return
        time.sleep(0.05)

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except PermissionError as exc:
        raise SignalLightError(f"Cannot stop existing signal worker {pid}: {exc}") from exc


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
