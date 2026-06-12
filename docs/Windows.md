# Windows + WSL2 Setup

This document records the full configuration needed to run Signal Light on a Windows machine with WSL2: the MCP2221A plugs into the Windows host, `usbipd-win` forwards it into WSL2, and Python + EasyMCP2221 drives the hardware from inside WSL2.

## Overview

```
MCP2221A (USB)
  └─ Windows ── usbipd bind+attach ──▶ WSL2 ── EasyMCP2221 ── signal-light CLI
                                                       └─ Claude Code hooks
```

## Windows Side

### usbipd-win

Download and install from [github.com/dorssel/usbipd-win](https://github.com/dorssel/usbipd-win). This provides the `usbipd` command on Windows, which can bind a local USB device and attach it to a running WSL2 instance.

Verified install location: `C:\Program Files\usbipd-win\usbipd.exe`

### Attach Script

Save the script below (e.g. `C:\Users\kalei\Desktop\mcp2221.ps1`). It finds the MCP2221A by USB VID:PID (`04d8:00dd`), binds it, and attaches it to WSL2.

**Must be run as Administrator** (right-click → "Run with PowerShell as Administrator"). `usbipd bind` requires elevation.

Full script:

```powershell
# mcp2221.ps1
# Attach MCP2221A traffic light to WSL2
$VID_PID = "04d8:00dd"

$busid = (usbipd list 2>$null | Select-String $VID_PID) -replace '^\s*(\S+).*', '$1'

if (-not $busid) {
    Write-Host "MCP2221A not found. Is the light plugged in?" -ForegroundColor Red
    pause
    exit 1
}

usbipd detach --busid $busid 2>$null
usbipd bind --busid $busid 2>$null
usbipd attach --wsl --busid $busid

if ($LASTEXITCODE -eq 0) {
    Write-Host "OK. Back in WSL, run: ./scripts/signal-light test" -ForegroundColor Green
} else {
    Write-Host "attach failed. Is WSL2 running?" -ForegroundColor Red
}

pause
```

If the script fails with garbled characters (mojibake), re-save the file as UTF-8 with BOM or ASCII. PowerShell 5.x does not handle UTF-8 without BOM reliably.

## WSL2 Side

### System packages

```bash
sudo apt install linux-tools-common usbutils
```

- `linux-tools-common` provides `/usr/bin/usbipd` and `/usr/bin/usbip`
- `usbutils` provides `lsusb`

### udev rules

By default only root can access USB and hidraw device nodes. Add two udev rules so any user can read/write the MCP2221A:

**`/etc/udev/rules.d/99-mcp2221a.rules`**

```
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="04d8", ATTRS{idProduct}=="00dd", MODE="0666"
```

**`/etc/udev/rules.d/99-mcp2221a-usb.rules`**

```
SUBSYSTEM=="usb", ATTRS{idVendor}=="04d8", ATTRS{idProduct}=="00dd", MODE="0666"
```

The USB rule is the one that actually matters at runtime: EasyMCP2221 accesses the device through libusb (`/dev/bus/usb/...`), not hidraw. The hidraw rule is a safety net for future access patterns.

After creating these files, re-plug the device (or re-run the attach script) for the rules to take effect. Verify with `ls -la /dev/bus/usb/001/` — the device node for MCP2221A should show `crw-rw-rw-`.

Rules only match VID `04d8` / PID `00dd` (MCP2221A). No other USB or hidraw devices are affected.

### Python dependencies

The project depends on `EasyMCP2221>=1.8.0` (which in turn depends on `hidapi`). Install with the project's own tooling:

```bash
cd ~/ClaudeCodeWorkSpace/vibecoding-signal-light
uv sync
```

Or install system-wide (verified path: miniconda3 `python3`, EasyMCP2221 1.8.4):

```bash
pip install EasyMCP2221>=1.8.0
```

The wrapper scripts at `./scripts/*` try `.venv/bin/python` first, then fall back to `python3`. No `.venv` is required if the packages are available at the system level.

### Claude Code hooks

Hooks are configured in `~/.claude/settings.json`. Every Claude Code event calls the signal-light wrapper script, which reads the event JSON from stdin and translates it to a lamp-language signal.

Only one env var is required beyond the project defaults:

```json
{
  "env": {
    "SIGNAL_LIGHT_STATE_DIR": "/tmp/signal-light"
  }
}
```

The full hook configuration is in [docs/LAMP_LANGUAGE.md](LAMP_LANGUAGE.md) (Claude Code settings.json Example section). Key points:

- **Hook command paths use the WSL2 Linux path** (`/home/kalei/ClaudeCodeWorkSpace/vibecoding-signal-light/scripts/claude-code-signal-hook`), not a Windows path.
- Claude Code passes the event as JSON on stdin; the wrapper needs no CLI argument.
- `PermissionRequest` uses a longer `timeout: 10`; all others use `timeout: 5`.

The `./scripts/install-hooks` wizard can automate this:

```bash
./scripts/install-hooks --agent claude-code -y
```

### Verify hardware

After running the PowerShell attach script:

```bash
# Confirm the device is visible
lsusb | grep 04d8

# Wiring test (red → yellow → green → all)
./scripts/signal-light test
```

## Daily Usage

1. Plug in the MCP2221A traffic light to a Windows USB port.
2. Run `mcp2221.ps1` as Administrator (right-click → Run with PowerShell as Administrator).
3. Start Claude Code. The light will reflect agent state automatically.

WSL2 retains the USB attachment until the device is physically unplugged or WSL2 restarts. After a Windows reboot, re-run step 2.
