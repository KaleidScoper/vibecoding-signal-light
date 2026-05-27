import io

from signal_light.agent_signals import SIGNALS
from signal_light import cli
from signal_light.codex_hook import CodexHookInput, choose_signal, session_key
from signal_light import runtime
from signal_light.runtime import aggregate_sessions, apply_session_signal


class RecordingLight:
    def __init__(self) -> None:
        self.states: list[tuple[bool, bool, bool]] = []
        self.brightness_states: list[tuple[float, float, float]] = []

    def write(self, *, green: bool = False, yellow: bool = False, red: bool = False) -> None:
        self.states.append((green, yellow, red))

    def write_brightness(self, *, green: float = 0.0, yellow: float = 0.0, red: float = 0.0) -> None:
        self.brightness_states.append((green, yellow, red))

    def off(self) -> None:
        self.write()


def test_idle_signal_leaves_green_on() -> None:
    light = RecordingLight()

    SIGNALS["idle"].play(light, speed=0.05)

    assert SIGNALS["idle"].repeat is False
    assert light.states[-1] == (True, False, False)


def test_working_signal_uses_soft_green_yellow_red_cycle() -> None:
    light = RecordingLight()

    SIGNALS["working"].play(light, speed=0.05, cycles=1)

    assert SIGNALS["working"].repeat is True
    assert len(light.brightness_states) == 27
    assert all(green > 0 and yellow == 0 and red == 0 for green, yellow, red in light.brightness_states[:9])
    assert all(green == 0 and yellow > 0 and red == 0 for green, yellow, red in light.brightness_states[9:18])
    assert all(green == 0 and yellow == 0 and red > 0 for green, yellow, red in light.brightness_states[18:27])
    assert light.brightness_states[0][0] < light.brightness_states[4][0]
    assert light.brightness_states[4][0] > light.brightness_states[8][0]


def test_attention_signal_flashes_yellow() -> None:
    light = RecordingLight()

    SIGNALS["attention"].play(light, speed=0.05, cycles=1)

    assert SIGNALS["attention"].repeat is True
    assert light.states[:2] == [(False, True, False), (False, False, False)]


def test_thinking_signal_uses_work_cycle() -> None:
    light = RecordingLight()

    SIGNALS["thinking"].play(light, speed=0.05, cycles=1)

    assert SIGNALS["thinking"].frames == SIGNALS["working"].frames
    assert len(light.brightness_states) == 27
    assert light.brightness_states[0] == (0.10, 0.0, 0.0)
    assert light.brightness_states[9] == (0.0, 0.10, 0.0)
    assert light.brightness_states[18] == (0.0, 0.0, 0.10)


def test_permission_signal_flashes_red() -> None:
    light = RecordingLight()

    SIGNALS["permission"].play(light, speed=0.05, cycles=1)

    assert SIGNALS["permission"].repeat is True
    assert light.states[:2] == [(False, False, True), (False, False, False)]


def test_session_end_returns_to_idle_green() -> None:
    light = RecordingLight()

    SIGNALS["session_end"].play(light, speed=0.05)

    assert light.states[-1] == (True, False, False)


def test_codex_stop_maps_to_turn_end() -> None:
    signal = choose_signal(CodexHookInput(event_name="Stop", payload={}))

    assert signal == "turn_end"


def test_failed_payload_maps_to_blocked() -> None:
    signal = choose_signal(
        CodexHookInput(
            event_name="PostToolUse",
            payload={"status": "failed"},
        )
    )

    assert signal == "blocked"


def test_structured_error_payload_maps_to_blocked() -> None:
    signal = choose_signal(
        CodexHookInput(
            event_name="PostToolUse",
            payload={"error": {"message": "command failed"}},
        )
    )

    assert signal == "blocked"


def test_prompt_text_containing_error_does_not_map_to_blocked() -> None:
    signal = choose_signal(
        CodexHookInput(
            event_name="UserPromptSubmit",
            payload={"prompt": "please fix this error"},
        )
    )

    assert signal == "thinking"


def test_success_status_does_not_become_unknown_signal() -> None:
    signal = choose_signal(
        CodexHookInput(
            event_name="PostToolUse",
            payload={"status": "success"},
        )
    )

    assert signal == "tool_done"


def test_aggregate_keeps_attention_over_other_working_session() -> None:
    aggregate = aggregate_sessions(
        {
            "a": {"signal": "attention", "updated_at": 1},
            "b": {"signal": "working", "updated_at": 1},
        }
    )

    assert aggregate == "attention"


def test_aggregate_keeps_permission_over_attention_and_working() -> None:
    aggregate = aggregate_sessions(
        {
            "a": {"signal": "attention", "updated_at": 1},
            "b": {"signal": "working", "updated_at": 1},
            "c": {"signal": "permission", "updated_at": 1},
        }
    )

    assert aggregate == "permission"


def test_aggregate_returns_working_when_any_session_is_working() -> None:
    aggregate = aggregate_sessions(
        {
            "a": {"signal": "idle", "updated_at": 1},
            "b": {"signal": "tool_done", "updated_at": 1},
        }
    )

    assert aggregate == "working"


def test_aggregate_returns_idle_for_empty_sessions() -> None:
    assert aggregate_sessions({}) == "idle"


def test_session_key_prefers_payload_session_id() -> None:
    key = session_key(
        CodexHookInput(event_name="Stop", payload={"session_id": "session-a", "cwd": "/tmp/x"}),
        {},
    )

    assert key == "session-a"


def test_session_key_falls_back_to_cwd() -> None:
    key = session_key(
        CodexHookInput(event_name="Stop", payload={"cwd": "/tmp/project"}),
        {},
    )

    assert key == "cwd:/tmp/project"


def test_session_key_ignores_turn_id_and_uses_cwd() -> None:
    key = session_key(
        CodexHookInput(event_name="Stop", payload={"turn_id": "turn-a", "cwd": "/tmp/project"}),
        {"CODEX_TURN_ID": "turn-env"},
    )

    assert key == "cwd:/tmp/project"


def test_cli_codex_hook_uses_session_aware_path(monkeypatch) -> None:
    calls: list[tuple[str, str, bool, bool]] = []
    monkeypatch.setattr("sys.stdin", io.StringIO('{"session_id":"session-a","event":"Stop"}'))
    monkeypatch.setattr(
        cli,
        "play_codex_hook_signal",
        lambda signal_name, *, session_key, dry_run=False, quiet=False: calls.append(
            (signal_name, session_key, dry_run, quiet)
        )
        or 0,
    )

    assert cli.main(["codex-hook", "--dry-run"]) == 0
    assert calls == [("turn_end", "session-a", True, True)]


def test_cli_codex_hook_without_event_uses_stdin_event(monkeypatch) -> None:
    calls: list[tuple[str, str, bool, bool]] = []
    monkeypatch.setattr("sys.stdin", io.StringIO('{"session_id":"session-a","event":"PermissionRequest"}'))
    monkeypatch.setattr(
        cli,
        "play_codex_hook_signal",
        lambda signal_name, *, session_key, dry_run=False, quiet=False: calls.append(
            (signal_name, session_key, dry_run, quiet)
        )
        or 0,
    )

    assert cli.main(["codex-hook", "--dry-run"]) == 0
    assert calls == [("permission", "session-a", True, True)]


def test_apply_session_signal_preserves_attention_over_other_work(tmp_path, monkeypatch) -> None:
    applied: list[str] = []
    monkeypatch.setattr(runtime, "STATE_DIR", tmp_path)
    monkeypatch.setattr(runtime, "SESSION_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(runtime, "LOCK_FILE", tmp_path / "state.lock")
    monkeypatch.setattr(runtime, "apply_signal", lambda signal, speed=1.0: applied.append(signal.name))
    monkeypatch.setattr(cli, "apply_signal", lambda signal, speed=1.0: applied.append(signal.name))
    monkeypatch.setattr(cli, "apply_signal", lambda signal, speed=1.0: applied.append(signal.name))

    assert apply_session_signal("session-a", "attention") == "attention"
    assert apply_session_signal("session-b", "working") == "attention"

    assert applied == ["attention", "attention"]


def test_apply_session_signal_escalates_permission_over_attention(tmp_path, monkeypatch) -> None:
    applied: list[str] = []
    monkeypatch.setattr(runtime, "STATE_DIR", tmp_path)
    monkeypatch.setattr(runtime, "SESSION_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(runtime, "LOCK_FILE", tmp_path / "state.lock")
    monkeypatch.setattr(runtime, "apply_signal", lambda signal, speed=1.0: applied.append(signal.name))
    monkeypatch.setattr(cli, "apply_signal", lambda signal, speed=1.0: applied.append(signal.name))
    monkeypatch.setattr(cli, "apply_signal", lambda signal, speed=1.0: applied.append(signal.name))

    assert apply_session_signal("session-a", "attention") == "attention"
    assert apply_session_signal("session-b", "permission") == "permission"

    assert applied == ["attention", "permission"]


def test_apply_session_signal_removes_session_on_end(tmp_path, monkeypatch) -> None:
    applied: list[str] = []
    monkeypatch.setattr(runtime, "STATE_DIR", tmp_path)
    monkeypatch.setattr(runtime, "SESSION_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(runtime, "LOCK_FILE", tmp_path / "state.lock")
    monkeypatch.setattr(runtime, "apply_signal", lambda signal, speed=1.0: applied.append(signal.name))

    assert apply_session_signal("session-a", "working") == "working"
    assert apply_session_signal("session-a", "session_end") == "idle"

    assert applied == ["working", "idle"]


def test_apply_session_signal_clears_non_urgent_session_on_turn_end(tmp_path, monkeypatch) -> None:
    applied: list[str] = []
    monkeypatch.setattr(runtime, "STATE_DIR", tmp_path)
    monkeypatch.setattr(runtime, "SESSION_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(runtime, "LOCK_FILE", tmp_path / "state.lock")
    monkeypatch.setattr(runtime, "apply_signal", lambda signal, speed=1.0: applied.append(signal.name))

    assert apply_session_signal("session-a", "working") == "working"
    assert apply_session_signal("session-a", "turn_end") == "idle"

    assert runtime.read_session_snapshot() == {"aggregate": "idle", "sessions": {}}
    assert applied == ["working", "idle"]


def test_apply_session_signal_keeps_permission_on_turn_end(tmp_path, monkeypatch) -> None:
    applied: list[str] = []
    monkeypatch.setattr(runtime, "STATE_DIR", tmp_path)
    monkeypatch.setattr(runtime, "SESSION_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(runtime, "LOCK_FILE", tmp_path / "state.lock")
    monkeypatch.setattr(runtime, "apply_signal", lambda signal, speed=1.0: applied.append(signal.name))

    assert apply_session_signal("session-a", "permission") == "permission"
    assert apply_session_signal("session-a", "turn_end") == "permission"

    assert runtime.read_session_snapshot()["aggregate"] == "permission"
    assert applied == ["permission", "permission"]


def test_manual_idle_clears_all_session_state(tmp_path, monkeypatch) -> None:
    applied: list[str] = []
    monkeypatch.setattr(runtime, "STATE_DIR", tmp_path)
    monkeypatch.setattr(runtime, "SESSION_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(runtime, "LOCK_FILE", tmp_path / "state.lock")
    monkeypatch.setattr(runtime, "apply_signal", lambda signal, speed=1.0: applied.append(signal.name))
    monkeypatch.setattr(cli, "apply_signal", lambda signal, speed=1.0: applied.append(signal.name))

    assert apply_session_signal("session-a", "attention") == "attention"
    assert cli.play_signal("idle") == 0
    assert runtime.read_session_snapshot() == {"aggregate": "idle", "sessions": {}}
    assert applied == ["attention", "idle"]


def test_manual_off_clears_all_session_state(tmp_path, monkeypatch) -> None:
    applied: list[str] = []
    monkeypatch.setattr(runtime, "STATE_DIR", tmp_path)
    monkeypatch.setattr(runtime, "SESSION_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(runtime, "LOCK_FILE", tmp_path / "state.lock")
    monkeypatch.setattr(runtime, "apply_signal", lambda signal, speed=1.0: applied.append(signal.name))
    monkeypatch.setattr(cli, "apply_signal", lambda signal, speed=1.0: applied.append(signal.name))

    assert apply_session_signal("session-a", "permission") == "permission"
    assert cli.play_signal("off") == 0
    assert runtime.read_session_snapshot() == {"aggregate": "idle", "sessions": {}}
    assert applied == ["permission", "off"]
