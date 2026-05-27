# signal-light

Traffic signal status lights for AI agent work.

The current hardware demo uses an MCP2221A GPIO adapter to drive a red/yellow/green traffic signal model. On top of that, this repository includes a small persistent status language and hook adapters for Codex and Claude Code so the light can show whether an AI agent is busy, waiting for you, or blocked.

## Quick Start

List the available signals:

```bash
./scripts/signal-light list
```

Preview a signal without touching hardware:

```bash
./scripts/signal-light play attention --dry-run
```

Run a wiring test on the MCP2221A:

```bash
./scripts/signal-light test
```

Play a real signal:

```bash
./scripts/signal-light play permission
./scripts/signal-light play done
```

## Claude Code Hook Usage

Claude Code passes event data as JSON on stdin, so the hook script needs no arguments:

```bash
echo '{"event":"PreToolUse","session_id":"abc"}' | ./scripts/claude-code-signal-hook
echo '{"event":"PermissionRequest","session_id":"abc"}' | ./scripts/claude-code-signal-hook
echo '{"event":"Stop","session_id":"abc"}' | ./scripts/claude-code-signal-hook
```

Add hooks to `~/.claude/settings.json` — see [docs/LAMP_LANGUAGE.md](docs/LAMP_LANGUAGE.md) for the full configuration example.

## Codex Hook Usage

The hook wrapper accepts a Codex hook event and plays the corresponding lamp signal:

```bash
./scripts/codex-signal-hook UserPromptSubmit
./scripts/codex-signal-hook PreToolUse
./scripts/codex-signal-hook PermissionRequest
./scripts/codex-signal-hook Stop
```

The status meaning is intentionally small:

- steady green: Codex is idle
- slow green-yellow-red work cycle: Codex is working
- flashing yellow: Codex explicitly needs you to read or continue
- flashing red: Codex needs permission or is blocked

Animated states are persistent: the work state keeps a slow green-yellow-red cycle. Drivers that support brightness can render it as a soft pulse; plain GPIO hardware uses steady on/off segments to avoid visible PWM flicker. Yellow and red flashes continue until the next Codex event changes the status. Run `./scripts/signal-light play idle` to return to green idle, or `./scripts/signal-light play off` to turn all lights off.

Codex hooks are session-aware. Each Codex session keeps its own latest state, and the physical light shows the highest-priority aggregate:

```text
red flashing > yellow flashing > green-yellow-red work cycle > steady green idle
```

That means one session waiting for permission will not be hidden by another session starting tool work.

See [docs/LAMP_LANGUAGE.md](docs/LAMP_LANGUAGE.md) for the complete lamp language and a `~/.codex/hooks.json` example.

## Hardware Defaults

Default GPIO mapping:

- `gp0`: green
- `gp1`: yellow
- `gp2`: red
- active-low output, where GPIO `LOW` means the light is on

Override the defaults with:

```bash
export SIGNAL_LIGHT_GREEN_PIN=gp0
export SIGNAL_LIGHT_YELLOW_PIN=gp1
export SIGNAL_LIGHT_RED_PIN=gp2
export SIGNAL_LIGHT_ACTIVE_LOW=1
```

Use `SIGNAL_LIGHT_ACTIVE_LOW=0` for active-high wiring.

The wrapper scripts use `python3` by default because Codex hooks should start quickly and avoid package-manager cache work. Set `SIGNAL_LIGHT_USE_UV=1` if you want the wrappers to run through `uv run`.
