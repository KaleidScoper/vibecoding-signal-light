#!/usr/bin/env python3
"""Simple MCP2221A GPIO LED test.

Wiring assumed by this script:

    3.3V -> LED anode
    LED cathode -> current-limiting resistor -> GP0/GP1/GP2/GP3

This is active-low wiring:

    GPIO LOW  = LED on
    GPIO HIGH = LED off
"""

from __future__ import annotations

import time

import EasyMCP2221


LED_PINS = ("gp0", "gp1", "gp2", "gp3")
STEP_SECONDS = 0.35


def write_leds(mcp: EasyMCP2221.Device, gp0: bool, gp1: bool, gp2: bool, gp3: bool) -> None:
    """Write LED states where True means LED on."""
    mcp.GPIO_write(
        gp0=not gp0,
        gp1=not gp1,
        gp2=not gp2,
        gp3=not gp3,
    )


def all_off(mcp: EasyMCP2221.Device) -> None:
    write_leds(mcp, False, False, False, False)


def setup() -> EasyMCP2221.Device:
    mcp = EasyMCP2221.Device()
    mcp.set_pin_function(
        gp0="GPIO_OUT",
        gp1="GPIO_OUT",
        gp2="GPIO_OUT",
        gp3="GPIO_OUT",
        out0=True,
        out1=True,
        out2=True,
        out3=True,
    )
    all_off(mcp)
    return mcp


def chase(mcp: EasyMCP2221.Device, loops: int = 4) -> None:
    for _ in range(loops):
        write_leds(mcp, True, False, False, False)
        time.sleep(STEP_SECONDS)
        write_leds(mcp, False, True, False, False)
        time.sleep(STEP_SECONDS)
        write_leds(mcp, False, False, True, False)
        time.sleep(STEP_SECONDS)
        write_leds(mcp, False, False, False, True)
        time.sleep(STEP_SECONDS)


def blink_all(mcp: EasyMCP2221.Device, loops: int = 3) -> None:
    for _ in range(loops):
        write_leds(mcp, True, True, True, True)
        time.sleep(0.4)
        all_off(mcp)
        time.sleep(0.4)


def main() -> int:
    mcp = setup()
    print("MCP2221A connected. Testing GP0, GP1, GP2, GP3 with active-low LEDs.")
    print("LOW = on, HIGH = off. Press Ctrl-C to stop.")

    try:
        blink_all(mcp)
        chase(mcp)
        blink_all(mcp)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        all_off(mcp)

    print("Done. All LEDs off.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
