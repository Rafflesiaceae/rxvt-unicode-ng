#!/usr/bin/env python3
"""Check automatic monitor rates and overrides using private Xvfb fixtures."""

import ctypes
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

# Reuse the existing PTY and Xvfb helpers without leaving bytecode in the tree.
sys.dont_write_bytecode = True
from latency import isolated_display
from rendering import Terminal


def check_rate(terminal, rate):
    time.sleep(0.05)
    values = []
    for i in range(8):
        before = len(terminal.visible_updates())
        start = time.monotonic()
        terminal.send(f"\rmeasurement {i}".encode())
        deadline = start + 1
        while len(terminal.visible_updates()) == before:
            if time.monotonic() > deadline:
                raise AssertionError("terminal did not present an update")
            time.sleep(0.001)
        stamp = float(terminal.visible_updates()[before][1])
        values.append((stamp - start) * 1000)
        time.sleep(0.025)
    expected = 1000 / rate if rate else 0
    measured = statistics.median(values)
    assert abs(measured - expected) < 4, (rate, measured, values)
    print(f"PASS: {rate:g} Hz scheduling, median delay {measured:.2f} ms", flush=True)


def main():
    binary = str(Path(sys.argv[1] if len(sys.argv) > 1 else "build/src/nrxvt").resolve())
    with tempfile.TemporaryDirectory(prefix="urxvt-refresh-rate-") as temporary:
        directory = Path(temporary)
        trace = directory / "render.so"
        monitors = directory / "monitors.so"
        subprocess.run(["cc", "-shared", "-fPIC", "-o", str(trace),
                        str(Path(__file__).with_name("render-probe.c")), "-ldl"], check=True)
        flags = subprocess.check_output(["pkg-config", "--cflags", "xrandr"], text=True).split()
        subprocess.run(["cc", "-shared", "-fPIC", "-Wall", "-Wextra", "-o", str(monitors),
                        str(Path(__file__).with_name("monitor-probe.c")), "-ldl", *flags], check=True)
        settings = directory / "monitors"

        def configure(left, right, left_flags=0):
            settings.write_text(f"{left} {left_flags} {right} 0\n")

        configure(144, 60)
        with isolated_display(directory) as env:
            env.update(LD_PRELOAD=f"{trace}:{monitors}", URXVT_TEST_MONITORS=str(settings))
            xlib = ctypes.CDLL("libX11.so.6")
            xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
            xlib.XOpenDisplay.restype = ctypes.c_void_p
            xlib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            xlib.XDefaultRootWindow.restype = ctypes.c_ulong
            xlib.XMoveWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int]
            xlib.XResizeWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_uint, ctypes.c_uint]
            xlib.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
            xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]
            randr = ctypes.CDLL("libXrandr.so.2")
            randr.XRRSetScreenSize.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
                                             ctypes.c_int, ctypes.c_int, ctypes.c_int]
            randr.XRRQueryVersion.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
                                            ctypes.POINTER(ctypes.c_int)]
            display = xlib.XOpenDisplay(env["DISPLAY"].encode())
            assert display
            major, minor = ctypes.c_int(1), ctypes.c_int(3)
            assert randr.XRRQueryVersion(display, ctypes.byref(major), ctypes.byref(minor))
            root = xlib.XDefaultRootWindow(display)
            serial = 0

            def notify():
                nonlocal serial
                serial += 1
                # Real RandR screen-change events refresh the interposed modes.
                randr.XRRSetScreenSize(display, root, 3840, 2160, 1000 + serial, 600)
                xlib.XSync(display, False)

            try:
                auto = ("+fps", "+refreshBatching", "-frameBuffering")
                terminal = Terminal(binary, directory, env, arguments=auto)
                try:
                    check_rate(terminal, 144)
                    parent = int(next(e for e in terminal.events() if e[0] == "window")[2])
                    xlib.XMoveWindow(display, parent, 450, 10)
                    xlib.XSync(display, False)
                    check_rate(terminal, 144)
                    configure(240, 60)
                    notify()
                    check_rate(terminal, 240)
                    configure(72, 60, 0x10)  # RR_Interlace reports field rate.
                    notify()
                    check_rate(terminal, 144)
                    configure(288, 60, 0x20)  # RR_DoubleScan halves the rate.
                    notify()
                    check_rate(terminal, 144)
                    configure(0, 60)
                    notify()
                    check_rate(terminal, 60)
                    configure(-1, 50)  # Ignore inactive outputs, even when faster.
                    notify()
                    check_rate(terminal, 50)
                    configure(-1, -1)
                    notify()
                    check_rate(terminal, 60)
                finally:
                    terminal.close()

                configure(144, 60)
                # Use the resource class so overrides survive binary renames.
                for value in (90, 0, -0.02):
                    terminal = Terminal(binary, directory, env,
                                        resources=(f"URxvt.refreshRate: {value}",),
                                        arguments=("+refreshBatching", "-frameBuffering"))
                    try:
                        expected = 50 if value < 0 else value
                        check_rate(terminal, expected)
                        configure(240, 60)
                        notify()
                        check_rate(terminal, expected)
                    finally:
                        terminal.close()
                configure(144, 60)
                terminal = Terminal(binary, directory, env, resources=("URxvt.refreshRate: 90",),
                                    arguments=("-fps", "144", "+refreshBatching", "-frameBuffering"))
                try:
                    check_rate(terminal, 144)
                finally:
                    terminal.close()
                terminal = Terminal(binary, directory, env,
                                    arguments=("+fps", "+refreshBatching", "+frameBuffering"))
                try:
                    check_rate(terminal, 144)
                finally:
                    terminal.close()
                terminal = Terminal(binary, directory, dict(env, URXVT_TEST_NO_RANDR="1"), arguments=auto)
                try:
                    check_rate(terminal, 60)
                finally:
                    terminal.close()
            finally:
                xlib.XCloseDisplay(display)


if __name__ == "__main__":
    main()
