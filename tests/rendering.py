#!/usr/bin/env python3
"""Exercise real X11 presentation without screenshots.

Run: python3 tests/rendering.py build/src/urxvt
Requires Xvfb, a C compiler and X11 development headers.
"""

import ctypes
import os
from pathlib import Path
import pty
import select
import subprocess
import sys
import tempfile
import time
import tty


def wait_until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("timed out waiting for terminal")


class Terminal:
    def __init__(self, binary, directory, env, font="fixed", resources=()):
        self.trace = directory / f"trace-{time.monotonic_ns()}"
        self.master, self.slave = pty.openpty()
        tty.setraw(self.slave)
        self.errors = tempfile.TemporaryFile()
        args = [binary, "-pty-fd", str(self.master), "-geometry", "20x4",
                "-fn", font, "+sb", "+bc"]
        for resource in resources:
            args.extend(["-xrm", resource])
        self.process = subprocess.Popen(
            args, pass_fds=(self.master,), stdout=subprocess.DEVNULL,
            stderr=self.errors, env=dict(env, URXVT_RENDER_TRACE=str(self.trace)))
        wait_until(lambda: self.presentations())
        self.send(b"\x1b[?25lready")
        time.sleep(0.08)

    def events(self):
        if not self.trace.exists():
            return []
        return [line.split() for line in self.trace.read_text().splitlines()]

    def presentations(self):
        return [e for e in self.events() if e[0] == "present"]

    def send(self, data):
        os.write(self.slave, data)

    def query(self, data, expected):
        self.send(data)
        received = b""
        deadline = time.monotonic() + 2
        while expected not in received and time.monotonic() < deadline:
            if select.select([self.slave], [], [], 0.1)[0]:
                received += os.read(self.slave, 4096)
        assert expected in received, (expected, received)

    def close(self):
        self.process.terminate()
        self.process.wait(timeout=2)
        os.close(self.master)
        os.close(self.slave)
        self.errors.seek(0)
        errors = self.errors.read().decode()
        self.errors.close()
        assert "X Error" not in errors, errors


def check_frames(terminal, xlib, display):
    before = len(terminal.presentations())
    # Mix default and coloured erases, decorations, glyphs and scrolling.
    terminal.send(b"\x1b[2J\x1b[H\x1b[4mtest\x1b[0m\r\n"
                  b"\xe2\x94\x80\r\n" * 12 + b"\x1b[44m\x1b[2J\x1b[0m")
    wait_until(lambda: len(terminal.presentations()) > before)
    assert not [e for e in terminal.events() if e[0] in ("clear", "fill", "draw")]
    window = next(e for e in terminal.events() if e[0] == "window")
    parent, child = map(int, window[2:])
    source = terminal.presentations()[-1][2]

    # An expose must copy the retained frame without replacing its pixmap.
    before = len(terminal.presentations())
    xlib.XClearArea(display, child, 0, 0, 10, 10, True)
    xlib.XSync(display, False)
    wait_until(lambda: len(terminal.presentations()) > before)
    assert terminal.presentations()[-1][2] == source

    # Resize through the parent, as a window manager would.
    xlib.XResizeWindow(display, parent, 320, 180)
    xlib.XSync(display, False)
    wait_until(lambda: terminal.presentations()[-1][2] != source)
    terminal.query(b"\x1b[6n", b"R")

    # Hidden windows must retain pending logical updates for the next map.
    xlib.XUnmapWindow(display, parent)
    xlib.XSync(display, False)
    time.sleep(0.03)
    before_paint = len([e for e in terminal.events() if e[0] == "paint"])
    terminal.send(b"\x1b[0m\x1b[2J\x1b[Hupdated while hidden")
    terminal.query(b"\x1b[6n", b"R")
    time.sleep(0.03)
    assert len([e for e in terminal.events() if e[0] == "paint"]) == before_paint
    xlib.XMapWindow(display, parent)
    xlib.XSync(display, False)
    wait_until(lambda: len([e for e in terminal.events() if e[0] == "paint"]) > before_paint)


def check_synchronized(terminal, xlib, display):
    terminal.query(b"\x1b[?2026$p", b"\x1b[?2026;2$y")
    before = len(terminal.presentations())
    # Fragment both the mode sequence and the following repaint across reads.
    terminal.send(b"\x1b[?20")
    time.sleep(0.01)
    terminal.send(b"26h\x1b[2J\x1b[Hpartial")
    terminal.query(b"\x1b[?2026$p", b"\x1b[?2026;1$y")
    time.sleep(0.04)
    assert len(terminal.presentations()) == before
    # Reverse video forces a direct parser refresh; it must also be held.
    terminal.send(b"\x1b[?5h\r\n" + b"line\r\n" * 40)
    terminal.query(b"\x1b[6n", b"R")
    assert len(terminal.presentations()) == before

    # Expose restores the old frame even while the logical screen changes.
    window = next(e for e in terminal.events() if e[0] == "window")
    child = int(window[3])
    xlib.XClearArea(display, child, 0, 0, 10, 10, True)
    xlib.XSync(display, False)
    wait_until(lambda: len(terminal.presentations()) > before)
    before = len(terminal.presentations())
    terminal.send(b"complete\x1b[?2026l")
    wait_until(lambda: len(terminal.presentations()) > before)
    terminal.query(b"\x1b[?2026$p", b"\x1b[?2026;2$y")

    # Resizing during a hold must keep the old frame until the end marker.
    before = len(terminal.presentations())
    source = terminal.presentations()[-1][2]
    terminal.send(b"\x1b[?2026hresize")
    terminal.query(b"\x1b[?2026$p", b"\x1b[?2026;1$y")
    xlib.XResizeWindow(display, int(window[2]), 400, 220)
    xlib.XSync(display, False)
    time.sleep(0.03)
    assert all(e[2] == source for e in terminal.presentations()[before:])
    terminal.send(b"\x1b[?2026l")
    wait_until(lambda: terminal.presentations()[-1][2] != source)

    # Unmatched begin markers must not freeze the display or extend the hold.
    before = len(terminal.presentations())
    started = time.monotonic()
    terminal.send(b"\x1b[?2026hwatchdog")
    for _ in range(4):
        time.sleep(0.025)
        terminal.send(b"\x1b[?2026h")
    wait_until(lambda: len(terminal.presentations()) > before, timeout=0.4)
    assert time.monotonic() - started < 0.24
    terminal.query(b"\x1b[?2026$p", b"\x1b[?2026;1$y")
    before = len(terminal.presentations())
    terminal.send(b"still responsive")
    wait_until(lambda: len(terminal.presentations()) > before)

    # Reset cancels a fresh hold and clears the advertised mode.
    terminal.send(b"\x1b[?2026h\x1bc")
    terminal.query(b"\x1b[?2026$p", b"\x1b[?2026;2$y")
    terminal.send(b"\x1b[?2026h\x1b[!p")
    terminal.query(b"\x1b[?2026$p", b"\x1b[?2026;2$y")
    terminal.send(b"\x1b[?2026s\x1b[?2026h\x1b[?2026r")
    terminal.query(b"\x1b[?2026$p", b"\x1b[?2026;2$y")
    assert not [e for e in terminal.events() if e[0] in ("clear", "fill")]


def check_batching(terminal):
    before = len(terminal.presentations())
    terminal.send(b"\x1b[2J\x1b[H")
    # Interleaved writes must coalesce, including parser-forced scroll refreshes.
    for _ in range(4):
        time.sleep(0.0005)
        terminal.send(b"line\r\n" * 8)
    wait_until(lambda: len(terminal.presentations()) > before)
    time.sleep(0.01)
    assert len(terminal.presentations()) == before + 1

    # A steady stream must hit the fixed deadline instead of postponing forever.
    before = len(terminal.presentations())
    deadline = time.monotonic() + 0.08
    while time.monotonic() < deadline:
        terminal.send(b"\rcontinuous")
        time.sleep(0.001)
    assert len(terminal.presentations()) >= before + 2
    assert not [e for e in terminal.events() if e[0] in ("clear", "fill")]
    time.sleep(0.03)


def check_frame_rate(terminal):
    before = len(terminal.presentations())
    deadline = time.monotonic() + 0.16
    while time.monotonic() < deadline:
        terminal.send(b"\rframe rate")
        time.sleep(0.001)
    time.sleep(0.06)
    times = [float(e[1]) for e in terminal.presentations()[before:]]
    assert len(times) >= 2
    assert all(b - a >= 0.045 for a, b in zip(times, times[1:])), times


def main():
    binary = str(Path(sys.argv[1] if len(sys.argv) > 1 else "build/src/urxvt").resolve())
    with tempfile.TemporaryDirectory(prefix="urxvt-rendering-") as temporary:
        directory = Path(temporary)
        probe = directory / "probe.so"
        # Seed a resource database on the otherwise empty Xvfb display so that
        # command-line -xrm overrides exercise the usual resource merge path.
        environment = directory / "Xenvironment"
        environment.write_text("URxvt.renderingTest: true\n")
        subprocess.run(["cc", "-shared", "-fPIC", "-o", str(probe),
                        str(Path(__file__).with_name("render-probe.c")), "-ldl"], check=True)
        read_fd, write_fd = os.pipe()
        with tempfile.TemporaryFile() as server_errors:
            server = subprocess.Popen(
                ["Xvfb", "-displayfd", str(write_fd), "-screen", "0", "800x600x24",
                 "-nolisten", "tcp"], pass_fds=(write_fd,), stderr=server_errors)
            os.close(write_fd)
            try:
                assert select.select([read_fd], [], [], 5)[0], "Xvfb did not start"
                display_name = ":" + os.read(read_fd, 32).decode().strip()
                assert display_name != ":", "Xvfb failed to allocate a display"
                env = dict(os.environ, DISPLAY=display_name, LD_PRELOAD=str(probe),
                           XDG_CONFIG_HOME=str(directory), LC_ALL="C.UTF-8",
                           XENVIRONMENT=str(environment))
                xlib = ctypes.CDLL("libX11.so.6")
                xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
                xlib.XOpenDisplay.restype = ctypes.c_void_p
                xlib.XClearArea.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                           ctypes.c_int, ctypes.c_int, ctypes.c_uint,
                                           ctypes.c_uint, ctypes.c_int]
                xlib.XResizeWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                              ctypes.c_uint, ctypes.c_uint]
                xlib.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
                xlib.XUnmapWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
                xlib.XMapWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
                xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]
                display = xlib.XOpenDisplay(display_name.encode())
                assert display, "could not open test display"
                try:
                    # Batching is on by default; the baseline variants cover the
                    # unbatched path explicitly.
                    unbatched = "URxvt.refreshBatching: false"
                    variants = (("fixed", (unbatched,)), ("xft:monospace:size=11", (unbatched,)),
                                ("xft:monospace:size=11", (unbatched, "URxvt.depth: 32",
                                 "URxvt.background: [50]black", "URxvt.foreground: [80]white")))
                    for font, resources in variants:
                        terminal = Terminal(binary, directory, env, font, resources)
                        try:
                            check_frames(terminal, xlib, display)
                            check_synchronized(terminal, xlib, display)
                        finally:
                            terminal.close()
                        print(f"PASS: frame presentation, expose and resize ({font})")
                        print(f"PASS: synchronized output, queries, watchdog and reset ({font})")
                    terminal = Terminal(binary, directory, env, resources=(
                        "URxvt.refreshBatching: true", "URxvt.refreshRate: 0"))
                    try:
                        check_batching(terminal)
                        check_synchronized(terminal, xlib, display)
                    finally:
                        terminal.close()
                    print("PASS: bounded batching and synchronized output with batching enabled")
                    terminal = Terminal(binary, directory, env, resources=(
                        "URxvt.refreshBatching: true", "URxvt.refreshRate: 20"))
                    try:
                        check_frame_rate(terminal)
                    finally:
                        terminal.close()
                    print("PASS: batching respects the configured frame rate")
                finally:
                    xlib.XCloseDisplay(display)
            finally:
                os.close(read_fd)
                server.terminate()
                server.wait(timeout=2)


if __name__ == "__main__":
    main()
