#!/usr/bin/env python3
"""Compare rendering options using isolated XTEST input and XDamage events."""

import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import pty
import platform
import select
import statistics
import subprocess
import tempfile
import termios
import tty


def positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def nonnegative(value):
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("must be a finite nonnegative number")
    return number


@contextlib.contextmanager
def isolated_display(directory):
    read_fd, write_fd = os.pipe()
    with tempfile.TemporaryFile() as errors:
        server = subprocess.Popen(
            ["Xvfb", "-displayfd", str(write_fd), "-screen", "0", "3840x2160x24",
             "-nolisten", "tcp"], pass_fds=(write_fd,), stdout=subprocess.DEVNULL, stderr=errors)
        os.close(write_fd)
        try:
            if not select.select([read_fd], [], [], 5)[0]:
                raise RuntimeError("Xvfb did not start within five seconds")
            display = os.read(read_fd, 32).decode().strip()
            if not display:
                errors.seek(0)
                raise RuntimeError("Xvfb failed: " + errors.read().decode())
            environment = directory / "Xenvironment"
            environment.write_text("URxvt.latencyTest: true\n")
            # Inherit HOME unchanged, but isolate plugins and X environment
            # resources. Explicit switches below override rendering resources.
            env = dict(os.environ, DISPLAY=":" + display, XENVIRONMENT=str(environment),
                       XDG_CONFIG_HOME=str(directory), LC_ALL="C.UTF-8")
            env.pop("LD_PRELOAD", None)
            yield env
        finally:
            os.close(read_fd)
            server.terminate()
            server.wait(timeout=2)


def run_case(binary, driver, env, args, frame, synchronized, batching):
    master, slave = pty.openpty()
    process = None
    try:
        tty.setraw(slave)
        if args.mode == "key":
            # Kernel echo gives each injected key a deterministic PTY round
            # trip without shell startup, completion or line-editor effects.
            attributes = termios.tcgetattr(slave)
            attributes[3] |= termios.ECHO
            termios.tcsetattr(slave, termios.TCSANOW, attributes)
        command = [str(binary), "-pty-fd", str(master), "-geometry", args.geometry,
                   "-fn", args.font, "-name", "urxvt-latency", "+sb", "+bc", "-fps", str(args.fps)]
        for name, value in (("frameBuffering", frame), ("synchronizedOutput", synchronized),
                            ("refreshBatching", batching)):
            command.append(("-" if value else "+") + name)
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(command, pass_fds=(master,), env=env,
                                       stdout=subprocess.DEVNULL, stderr=errors)
            # Keep cursor animation out of the measured damage stream.
            os.write(slave, b"\x1b[?25l\x1b[2J\x1b[H")
            timeout = 10 + (args.samples + args.warmup) * (
                2 + args.interval_ms / 1000 + args.gap_ms / 1000)
            measured = subprocess.run(
                [str(driver), str(process.pid), str(slave), str(args.samples), args.mode,
                 str(args.interval_ms), str(args.gap_ms), str(args.warmup)],
                pass_fds=(slave,), env=env, capture_output=True, text=True, timeout=timeout)
            process.terminate()
            process.wait(timeout=2)
            errors.seek(0)
            terminal_errors = errors.read().decode()
            if measured.returncode or "X Error" in terminal_errors:
                raise RuntimeError(measured.stderr + terminal_errors)
        values = [float(line) for line in measured.stdout.splitlines()]
        if len(values) != args.samples:
            raise RuntimeError(f"Expected {args.samples} measurements, got {len(values)}")
        return {
            "frame_buffering": frame, "synchronized_output": synchronized,
            "refresh_batching": batching, "median_ms": statistics.median(values),
            "p95_ms": sorted(values)[math.ceil(len(values) * 0.95) - 1],
            "maximum_ms": max(values), "minimum_ms": min(values),
            "samples_ms": values, "text_geometry": measured.stderr.strip(),
        }
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=2)
        os.close(master)
        os.close(slave)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", nargs="?", default="build/src/urxvt")
    parser.add_argument("--samples", type=positive, default=30)
    parser.add_argument("--warmup", type=positive, default=5)
    parser.add_argument("--mode", choices=("key", "output", "synchronized", "watchdog"), default="key")
    parser.add_argument("--fps", type=nonnegative, default=60,
                        help="configured frame-rate limit; 0 disables the limit")
    parser.add_argument("--interval-ms", type=nonnegative, default=40)
    parser.add_argument("--gap-ms", type=nonnegative, default=20)
    parser.add_argument("--geometry", default="120x40")
    parser.add_argument("--font", default="xft:monospace:size=11")
    parser.add_argument("--json", type=Path, help="save raw measurements and run metadata")
    args = parser.parse_args()
    binary = Path(args.binary).resolve(strict=True)
    report = {
        "binary": str(binary), "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "mode": args.mode, "fps": args.fps, "geometry": args.geometry, "font": args.font,
        "samples": args.samples, "warmup": args.warmup, "interval_ms": args.interval_ms,
        "gap_ms": args.gap_ms, "backend": "isolated Xvfb, XTEST and XDamage",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
        "metric": "stimulus to first observed text-window damage, in milliseconds",
        "cases": [],
    }
    with tempfile.TemporaryDirectory(prefix="urxvt-latency-") as temporary:
        directory = Path(temporary)
        driver = directory / "latency-driver"
        flags = subprocess.check_output(
            ["pkg-config", "--cflags", "--libs", "x11", "xdamage", "xtst"], text=True).split()
        subprocess.run(["cc", "-O2", "-Wall", "-Wextra", "-o", str(driver),
                        str(Path(__file__).with_name("latency-driver.c")), *flags], check=True)
        rate = f"{args.fps:g} fps" if args.fps else "unlimited refresh rate"
        print(f"Mode: {args.mode}; {args.samples} samples/case; {rate}", flush=True)
        print("Milliseconds to first X server window update; physical display latency is excluded.", flush=True)
        print("frame sync batch | median      p95      max", flush=True)
        with isolated_display(directory) as env:
            for frame, synchronized, batching in itertools.product((False, True), repeat=3):
                case = run_case(binary, driver, env, args, frame, synchronized, batching)
                report["cases"].append(case)
                print(f"{int(frame):5} {int(synchronized):4} {int(batching):5} | "
                      f"{case['median_ms']:7.3f} {case['p95_ms']:8.3f} {case['maximum_ms']:8.3f}", flush=True)
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n")
        print(f"Raw measurements: {args.json}")


if __name__ == "__main__":
    main()
