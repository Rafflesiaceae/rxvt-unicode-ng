# Run all harnesses

```sh
./dev.py test
```

This configures and builds the development binary if needed, then runs the
rendering checks, refresh-rate checks and default latency benchmark in sequence.
It stops on the first failure. Use `-j N` to set the number of build jobs.
The dependencies for each harness are listed below.

# Startup, memory and CPU benchmarks

Build the binary first, then run the Linux resource benchmark separately:

```sh
./dev.py build
python3 tests/benchmark.py build/src/nrxvt --output-dir /tmp/urxvt-baseline

# Run the same workloads against the system urxvt.
python3 tests/benchmark.py /usr/bin/urxvt --output-dir /tmp/urxvt-system-baseline
```

It requires Xvfb, Linux `/proc` access, Xft support in the binary and a usable
`xft:monospace` font. Build with frills and X resources enabled, as with the other
harnesses. The terminal, private X server and Python workload producer
are pinned to logical CPUs 0, 2 and 4 respectively. These must be available CPUs
on separate physical cores; use `--cpu`, `--xvfb-cpu` and `--driver-cpu` to choose
others. On an SMT machine, do not assign two roles to sibling threads. The script
checks affinity and records governor, turbo, CPU model and system load settings.
It does not change system power settings or reserve cores against other tasks.

The default run measures 50 startup samples after five warmups, three idle
intervals, three repetitions of each approximately 16 MiB output workload and
three repetitions of a three-second paced rendering workload. Font comparisons
are interleaved, and throughput comparisons use a fixed randomized order.
Results describe warm caches; the benchmark does not flush system caches.
Avoid other CPU-heavy work during the run, and repeat comparisons sequentially.

Startup includes process creation through the first PTY cursor-position reply,
plus a separate start-and-exit measurement using `/bin/true`. Neither measures
shell initialization or physical display latency. Idle measurements hide the
cursor. Throughput covers ASCII scrolling, ANSI colors and mixed Unicode with
and without scrollback. A parser reply acknowledges the full payload; CPU and
memory samples follow an 80 ms settling interval for the scheduled final draw.
Terminal and Xvfb CPU times are reported separately from the Python producer.
Memory includes RSS, proportional set size (PSS) and private pages from
`smaps_rollup`, both before and after filling scrollback.

The larger 240x80 rendering workload submits changing text at 60 updates per
second using the selected binary's default rendering behavior. It uses standard
urxvt options, so it also runs on `/usr/bin/urxvt`. Rendering-option comparisons
belong to the separate latency and rendering harnesses. Submitted updates are
counted, not presented frames, so lower CPU use can also mean fewer rendered
frames. Xvfb uses software rendering: its memory and CPU costs do not represent
the user's GPU or compositor. No screenshots or desktop input are used.

The output directory retains `results.json` with every sample, executable hashes,
run settings and metadata. Use a new directory for each run. Partial results are
marked `completed: false`; a successful run verifies that the executable hash
did not change. The executable is used directly, so do not rebuild it mid-run.

Additional options:

```sh
# Include startup with the shipped example plugins.
python3 tests/benchmark.py build/src/nrxvt --plugins src/lua

# Also sample CPU hotspots when perf permissions allow it.
python3 tests/benchmark.py build/src/nrxvt --perf

# Add phase timestamps from an existing instrumented development binary.
python3 tests/benchmark.py build/src/nrxvt --profile-binary build/profile/build/src/nrxvt

# Short smoke run when developing the harness.
python3 tests/benchmark.py build/src/nrxvt --startup-samples 2 --warmup 1 --repeats 1 --mib 1 --idle-seconds .1 --paced-seconds .2
```

Optional perf sampling saves recordings and text reports for each output
workload. If sampling is denied, the resource measurements are retained and the
reason is saved in the perf log. Instrumented binaries can be produced with
`./dev.py profile-startup`; phase timings are separate from unmodified timings.

# Rendering checks

Run the functional integration checks with:

```sh
python3 tests/rendering.py build/src/nrxvt
```

They require Xvfb, a C compiler, X11 development headers and Liberation Mono
for the glyph-overflow check. They trace X11 requests and compare neighboring
rows in memory without saving screenshots.

# Lua bars

```sh
python3 tests/bars.py build/src/nrxvt
```

Requires a Lua-enabled build, Xvfb, a C compiler, and X11/XTEST libraries. The harness uses an isolated display and traces geometry, fill, and copy requests without reading pixels or saving screenshots. It covers four-edge docking and priorities, nested sizing, atomic declaration rejection, accumulated damage, bar-only presentation, outside dragging and capture cancellation, runtime reservations, tiny windows, callback closure/errors, core/Xft fonts, the proportional Lua scrollbar, and coexistence with the native scrollbar. Bounded CPU samples include complete Lua submission and native diffing; they exclude presentation and are not end-to-end frame-rate measurements.

# Monitor refresh detection

With RandR support, check the maximum rate across active displays, window moves,
live mode changes, interlace/doublescan flags, unavailable timings and
explicit resource overrides:

```sh
python3 tests/refresh-rate.py build/src/nrxvt
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
python3 tests/latency.py build/src/nrxvt --json /tmp/urxvt-latency.json
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
python3 tests/latency.py build/src/nrxvt --mode output

# An application starts an update, writes text, then ends it 20 ms later.
python3 tests/latency.py build/src/nrxvt --mode synchronized --gap-ms 20

# An application omits its end marker, exercising the 150 ms watchdog.
python3 tests/latency.py build/src/nrxvt --mode watchdog --samples 3 --warmup 1

# Override automatic monitor detection with an explicit limit.
python3 tests/latency.py build/src/nrxvt --fps 144

# Remove the refresh-rate wait to isolate rendering work.
python3 tests/latency.py build/src/nrxvt --fps 0

# Compare a larger window using the same font and workload.
python3 tests/latency.py build/src/nrxvt --geometry 240x80
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
