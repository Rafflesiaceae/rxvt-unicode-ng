#!/usr/bin/env python3
"""Exercise real X11 presentation without screenshots.

Run: python3 tests/rendering.py build/src/nrxvt
Requires Xvfb, a C compiler and X11 development headers.
"""

import ctypes
import itertools
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
    def __init__(self, binary, directory, env, font="fixed", resources=(), arguments=()):
        self.trace = directory / f"trace-{time.monotonic_ns()}"
        self.master, self.slave = pty.openpty()
        tty.setraw(self.slave)
        self.errors = tempfile.TemporaryFile()
        args = [binary, "-pty-fd", str(self.master), "-geometry", "20x4",
                "-fn", font, "+sb", "+bc"]
        args.extend(arguments)
        for resource in resources:
            args.extend(["-xrm", resource])
        self.process = subprocess.Popen(
            args, pass_fds=(self.master,), stdout=subprocess.DEVNULL,
            stderr=self.errors, env=dict(env, URXVT_RENDER_TRACE=str(self.trace)))
        wait_until(lambda: self.visible_updates())
        self.send(b"\x1b[?25lready")
        time.sleep(0.08)

    def events(self):
        if not self.trace.exists():
            return []
        return [line.split() for line in self.trace.read_text().splitlines()]

    def presentations(self):
        return [e for e in self.events() if e[0] == "present"]

    def visible_updates(self):
        # Include direct drawing, where no completed-frame copy is issued.
        return [e for e in self.events() if e[0] in ("present", "fill", "draw", "clear")]

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


def check_glyph_overflow(terminal, xlib, display):
    child = int(next(e for e in terminal.events() if e[0] == "window")[3])
    root = ctypes.c_ulong()
    x, y = ctypes.c_int(), ctypes.c_int()
    width, height, border, depth = (ctypes.c_uint() for _ in range(4))
    assert xlib.XGetGeometry(display, child, ctypes.byref(root), ctypes.byref(x),
                             ctypes.byref(y), ctypes.byref(width), ctypes.byref(height),
                             ctypes.byref(border), ctypes.byref(depth))
    row_height = height.value // 4

    def paint(data):
        before = len(terminal.presentations())
        terminal.send(data)
        wait_until(lambda: len(terminal.presentations()) > before)
        time.sleep(0.02)

    def pixels(row):
        # Compare pixels in memory; no screenshot files are created.
        image = xlib.XGetImage(display, child, 0, row * row_height,
                              width.value, row_height, ctypes.c_ulong(-1), 2)
        assert image
        try:
            return tuple(xlib.XGetPixel(image, x, y)
                         for y in range(row_height) for x in range(width.value))
        finally:
            xlib.XDestroyImage(image)

    paint(b"\x1b[0m\x1b[2J\x1b[H")
    neighbors = pixels(0), pixels(2)
    blank = pixels(1)
    # Liberation Mono's stacked accent and script g extend above/below its
    # advertised line metrics. Only the middle row should acquire ink.
    paint("\x1b[2;3H\u1e4c\u210a".encode())
    assert pixels(1) != blank, "overflow glyphs were not drawn"
    assert (pixels(0), pixels(2)) == neighbors, "glyphs painted into neighboring rows"
    paint(b"\x1b[2;1H\x1b[2K")
    assert pixels(1) == blank, "erasing the glyph row left pixels behind"
    assert (pixels(0), pixels(2)) == neighbors, "erasing the glyph row left neighboring artifacts"


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


def check_configuration(terminal, frame_buffering, synchronized):
    assert bool([e for e in terminal.events() if e[0] == "frame"]) == frame_buffering
    status = b"2" if synchronized else b"0"
    terminal.query(b"\x1b[?2026$p", b"\x1b[?2026;" + status + b"$y")
    before = len(terminal.visible_updates())
    terminal.send(b"\x1b[?2026h\x1b[2J\x1b[Hconfiguration")
    if synchronized:
        terminal.query(b"\x1b[?2026$p", b"\x1b[?2026;1$y")
        time.sleep(0.03)
        assert len(terminal.visible_updates()) == before
    else:
        # An opt-out must disable actual holds, not just capability reporting.
        wait_until(lambda: len(terminal.visible_updates()) > before, timeout=0.1)
    terminal.send(b"\x1b[?2026l")
    wait_until(lambda: len(terminal.visible_updates()) > before)
    terminal.query(b"\x1b[?2026$p", b"\x1b[?2026;" + status + b"$y")
    if not synchronized:
        terminal.send(b"\x1b[?2026s\x1b[?2026h\x1b[?2026r\x1b[?2026t")
        terminal.query(b"\x1b[?2026$p", b"\x1b[?2026;0$y")
        before = len(terminal.visible_updates())
        terminal.send(b"\rno hold")
        wait_until(lambda: len(terminal.visible_updates()) > before, timeout=0.1)


def check_direct_drawing(terminal, xlib, display):
    window = next(e for e in terminal.events() if e[0] == "window")
    parent, child = map(int, window[2:])
    before = len(terminal.visible_updates())
    terminal.send(b"\x1b[2J\x1b[Hdirect drawing")
    wait_until(lambda: len(terminal.visible_updates()) > before)

    # Without a retained frame, expose must invalidate cells and redraw them.
    before = len(terminal.visible_updates())
    xlib.XClearArea(display, child, 0, 0, 40, 20, True)
    xlib.XSync(display, False)
    wait_until(lambda: len(terminal.visible_updates()) > before)
    before = len(terminal.visible_updates())
    xlib.XResizeWindow(display, parent, 320, 180)
    xlib.XSync(display, False)
    wait_until(lambda: len(terminal.visible_updates()) > before)
    time.sleep(0.03)

    # An exposed region during a hold must wait for the end marker to redraw.
    before = len(terminal.visible_updates())
    terminal.send(b"\x1b[?2026h\x1b[2J\x1b[Hheld direct drawing")
    terminal.query(b"\x1b[?2026$p", b"\x1b[?2026;1$y")
    xlib.XClearArea(display, child, 0, 0, 40, 20, True)
    xlib.XSync(display, False)
    time.sleep(0.03)
    assert len(terminal.visible_updates()) == before
    terminal.send(b"\x1b[?2026l")
    wait_until(lambda: len(terminal.visible_updates()) > before)

    # The watchdog must also release direct drawing with no retained pixmap.
    before = len(terminal.visible_updates())
    terminal.send(b"\x1b[?2026hwatchdog")
    wait_until(lambda: len(terminal.visible_updates()) > before, timeout=0.3)
    terminal.send(b"\x1b[?2026l")
    time.sleep(0.03)

    xlib.XUnmapWindow(display, parent)
    xlib.XSync(display, False)
    time.sleep(0.03)
    before = len(terminal.visible_updates())
    terminal.send(b"\x1b[2J\x1b[Hhidden direct update")
    terminal.query(b"\x1b[6n", b"R")
    time.sleep(0.03)
    assert len(terminal.visible_updates()) == before
    xlib.XMapWindow(display, parent)
    xlib.XSync(display, False)
    wait_until(lambda: len(terminal.visible_updates()) > before)
    assert not [e for e in terminal.events() if e[0] == "frame"]


def main():
    binary = str(Path(sys.argv[1] if len(sys.argv) > 1 else "build/src/nrxvt").resolve())
    with tempfile.TemporaryDirectory(prefix="urxvt-rendering-") as temporary:
        directory = Path(temporary)
        probe = directory / "probe.so"
        # Seed a resource database on the otherwise empty Xvfb display so that
        # command-line -xrm overrides exercise the usual resource merge path.
        environment = directory / "Xenvironment"
        environment.write_text("NRxvt.renderingTest: true\n")
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
                xlib.XGetGeometry.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                    ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
                    ctypes.POINTER(ctypes.c_int), *([ctypes.POINTER(ctypes.c_uint)] * 4)]
                xlib.XGetImage.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                    ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
                    ctypes.c_ulong, ctypes.c_int]
                xlib.XGetImage.restype = ctypes.c_void_p
                xlib.XGetPixel.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
                xlib.XGetPixel.restype = ctypes.c_ulong
                xlib.XDestroyImage.argtypes = [ctypes.c_void_p]
                display = xlib.XOpenDisplay(display_name.encode())
                assert display, "could not open test display"
                try:
                    # Batching is on by default; the baseline checks cover the
                    # unbatched path explicitly.
                    unbatched = "NRxvt.refreshBatching: false"
                    for buffered in (True, False):
                        terminal = Terminal(binary, directory, env,
                            "xft:Liberation Mono:size=11", resources=(
                                "NRxvt.frameBuffering: true", "NRxvt.lineSpace: 0",
                                unbatched, f"NRxvt.buffered: {str(buffered).lower()}"))
                        try:
                            check_glyph_overflow(terminal, xlib, display)
                        finally:
                            terminal.close()
                    print("PASS: tall Xft glyphs stay within their row and erase cleanly")
                    variants = (("fixed", (unbatched,)), ("xft:monospace:size=11", (unbatched,)),
                                ("xft:monospace:size=11", (unbatched, "NRxvt.depth: 32",
                                 "NRxvt.background: [50]black", "NRxvt.foreground: [80]white")))
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
                        "NRxvt.refreshBatching: true", "NRxvt.refreshRate: 0"))
                    try:
                        check_batching(terminal)
                        check_synchronized(terminal, xlib, display)
                    finally:
                        terminal.close()
                    print("PASS: bounded batching and synchronized output with batching enabled")
                    terminal = Terminal(binary, directory, env, resources=(
                        "NRxvt.refreshBatching: true", "NRxvt.refreshRate: 20"))
                    try:
                        check_frame_rate(terminal)
                    finally:
                        terminal.close()
                    print("PASS: batching respects the configured frame rate")

                    # Exercise all three startup switches independently.
                    for frame, synchronized, batching in itertools.product((False, True), repeat=3):
                        resources = tuple(f"NRxvt.{name}: {str(value).lower()}" for name, value in (
                            ("frameBuffering", frame), ("synchronizedOutput", synchronized),
                            ("refreshBatching", batching)))
                        terminal = Terminal(binary, directory, env, resources=resources)
                        try:
                            check_configuration(terminal, frame, synchronized)
                        finally:
                            terminal.close()
                    print("PASS: all eight rendering configuration combinations")

                    for font, buffered in (("fixed", True), ("xft:monospace:size=11", True),
                                           ("xft:monospace:size=11", False)):
                        resources = ("NRxvt.frameBuffering: false",
                                     f"NRxvt.buffered: {str(buffered).lower()}")
                        terminal = Terminal(binary, directory, env, font, resources)
                        try:
                            check_direct_drawing(terminal, xlib, display)
                        finally:
                            terminal.close()
                    print("PASS: direct drawing, expose, resize, synchronization and Xft buffering")

                    terminal = Terminal(binary, directory, env, "xft:monospace:size=11",
                                        ("NRxvt.buffered: false",))
                    try:
                        check_frames(terminal, xlib, display)
                    finally:
                        terminal.close()
                    print("PASS: frame buffering is independent of Xft text buffering")
                finally:
                    xlib.XCloseDisplay(display)
            finally:
                os.close(read_fd)
                server.terminate()
                server.wait(timeout=2)


if __name__ == "__main__":
    main()
