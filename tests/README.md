# Rendering checks

Run the functional integration checks with:

```sh
python3 tests/rendering.py build/src/urxvt
```

They require Xvfb, a C compiler and X11 development headers. They trace X11
requests without capturing screenshots.

# Monitor refresh detection

With RandR support, check the maximum rate across active displays, window moves,
live mode changes, interlace/doublescan flags, unavailable timings and
explicit resource overrides:

```sh
python3 tests/refresh-rate.py build/src/urxvt
```

This requires RandR development headers in addition to the rendering test
dependencies. The test supplies deterministic CRTC mode timings on a private
Xvfb display and checks scheduled drawing delays; it does not change the user's
display settings.

# Latency measurements

The latency benchmark launches its own Xvfb server and compares all eight
combinations of `frameBuffering`, `synchronizedOutput` and `refreshBatching`.
It requires a C compiler, pkg-config and the X11, XDamage and XTEST development
packages. Use a build with frills and X resources enabled, as with the functional
checks. The binary must include the three rendering configuration switches.

```sh
python3 tests/latency.py build/src/urxvt --json /tmp/urxvt-latency.json
```

The default test injects XTEST key events into the isolated terminal. The
PTY line discipline echoes each key, and XDamage reports when the X server
updates the text window. Each case has five warmup samples and 30 measured
samples, separated by 40 milliseconds after each response. No shell, plugin or
instrumentation library participates in the measured echo path.

In the table, `1` means enabled and `0` means disabled. Results include median,
nearest-rank 95th percentile and maximum latency in
milliseconds. JSON output preserves every sample, the executable hash, text
window dimensions and the run settings. Results are measurements, not pass/fail
thresholds; CPU scheduling and machine load affect them. Run comparisons
sequentially, repeat them when needed, and keep the machine's workload similar.

Other workloads are available:

```sh
# PTY output to the first window update, without keyboard delivery or echo.
python3 tests/latency.py build/src/urxvt --mode output

# An application starts an update, writes text, then ends it 20 ms later.
python3 tests/latency.py build/src/urxvt --mode synchronized --gap-ms 20

# An application omits its end marker, exercising the 150 ms watchdog.
python3 tests/latency.py build/src/urxvt --mode watchdog --samples 3 --warmup 1

# Override automatic monitor detection with an explicit limit.
python3 tests/latency.py build/src/urxvt --fps 144

# Remove the refresh-rate wait to isolate rendering work.
python3 tests/latency.py build/src/urxvt --fps 0

# Compare a larger window using the same font and workload.
python3 tests/latency.py build/src/urxvt --geometry 240x80
```

The synchronized workload starts its timer before the begin marker; the configured
gap is part of the application update time. When synchronization is disabled,
the benchmark can observe an update before the gap ends. The watchdog workload
sends an end marker after the first update to clean up before the next sample.

The endpoint is **the first text-window damage observed by the driver**, which
includes X server processing and notification delivery. Direct drawing may
damage the background before glyph drawing completes. This does not measure a
completed frame, compositor scheduling, monitor scanout, physical keyboard
hardware or actual key-to-photon latency. Xvfb is a software X server, so results
also cannot establish the cost of copies on the user's actual GPU or compositor.
The test captures no screenshots and does not send input to the user's display.

The default refresh rate uses the highest active display rate. Xvfb often provides no
usable mode timings, in which case automatic detection falls back to 60 Hz.
It does not discover the host's physical monitor rate; use `--fps` for an explicit
rate or the monitor fixtures above to exercise detection.
