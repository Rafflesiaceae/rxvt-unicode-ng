#!/usr/bin/env python3
"""Benchmark startup, memory and CPU use on Linux with a private Xvfb server."""

import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import pty
import random
import re
import select
import shutil
import statistics
import subprocess
import tempfile
import time
import tty


def positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError('must be positive')
    return number


def duration(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('must be finite and positive')
    return number


@contextlib.contextmanager
def affinity(cpu):
    # Children inherit affinity across exec; avoid taskset's extra executable
    # startup and preexec_fn's extra Python work in the measured child.
    previous = os.sched_getaffinity(0)
    os.sched_setaffinity(0, {cpu})
    try:
        yield
    finally:
        os.sched_setaffinity(0, previous)


def spawn(command, cpu, **kwargs):
    with affinity(cpu):
        return subprocess.Popen(command, **kwargs)


def cpu_seconds(pid):
    # schedstat's first field is execution time, excluding time spent waiting
    # for the CPU. Unlike /proc/stat ticks it resolves short workloads.
    return int(Path(f'/proc/{pid}/schedstat').read_text().split()[0]) / 1e9


def memory_kib(pid):
    values = {}
    for line in Path(f'/proc/{pid}/smaps_rollup').read_text().splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[2] == 'kB':
            values[fields[0].rstrip(':')] = int(fields[1])
    return values


def read_optional(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


@contextlib.contextmanager
def isolated_display(directory, cpu):
    read_fd, write_fd = os.pipe()
    with (directory / 'xvfb.log').open('wb') as errors:
        try:
            # A persistent server retains its font cache between launches.
            # Disabling TCP keeps all test connections local.
            server = spawn(['Xvfb', '-displayfd', str(write_fd), '-screen', '0',
                            '3840x2160x24', '-nolisten', 'tcp', '-noreset'], cpu,
                           pass_fds=(write_fd,), stdout=subprocess.DEVNULL, stderr=errors)
        finally:
            os.close(write_fd)
        try:
            if not select.select([read_fd], [], [], 5)[0]:
                raise RuntimeError('Xvfb did not start within five seconds')
            name = os.read(read_fd, 32).decode().strip()
            if not name:
                raise RuntimeError(f'Xvfb failed; see {directory / "xvfb.log"}')
            assert os.sched_getaffinity(server.pid) == {cpu}
            environment = directory / 'Xenvironment'
            environment.write_text('URxvt.benchmark: true\n')
            # A nonempty resource database prevents loading ~/.Xdefaults.
            # An empty plugin directory excludes user extensions from baseline.
            env = dict(os.environ, DISPLAY=':' + name, LC_ALL='C.UTF-8',
                       XENVIRONMENT=str(environment), XDG_CONFIG_HOME=str(directory / 'empty'))
            env.pop('LD_PRELOAD', None)
            env['XMODIFIERS'] = '@im=none'
            yield env, server.pid
        finally:
            os.close(read_fd)
            server.terminate()
            server.wait(timeout=5)


class Terminal:
    def __init__(self, binary, env, args, cpu, directory):
        self.master, self.slave = pty.openpty()
        tty.setraw(self.slave)
        os.set_blocking(self.slave, False)
        self.errors = tempfile.TemporaryFile(dir=directory)
        self.process = None
        self.ready_ms = 0
        try:
            start = time.perf_counter()
            self.process = spawn([str(binary), '-pty-fd', str(self.master), '+bc', *args],
                                 cpu, pass_fds=(self.master,), env=env,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=self.errors)
            # Hide the cursor so periodic animation does not affect idle CPU.
            self.send(b'\x1b[?25l')
            self.ready_ms = (time.perf_counter() - start) * 1000
            assert os.sched_getaffinity(self.process.pid) == {cpu}
        except BaseException:
            self.errors.seek(0)
            errors = self.errors.read().decode(errors='replace')
            if errors:
                print(errors, flush=True)
            self.close()
            raise

    def send(self, data):
        # A cursor-position reply proves that the parser reached the end of
        # the payload. It does not promise the final pixels have been drawn.
        view = memoryview(data + b'\x1b[6n')
        reply = b''
        deadline = time.monotonic() + 30
        while view or not re.search(rb'\x1b\[\d+;\d+R', reply):
            if self.process.poll() is not None:
                raise RuntimeError(f'terminal exited with status {self.process.returncode}')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError('PTY parser acknowledgement timed out')
            readable, writable, _ = select.select([self.slave], [self.slave] if view else [],
                                                 [], min(remaining, .1))
            if writable:
                try:
                    view = view[os.write(self.slave, view):]
                except BlockingIOError:
                    pass
            if readable:
                reply += os.read(self.slave, 4096)

    def close(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=5)
        os.close(self.master)
        os.close(self.slave)
        self.errors.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def measured_workload(term, server_pid, payload):
    t0, x0 = cpu_seconds(term.process.pid), cpu_seconds(server_pid)
    start = time.perf_counter()
    term.send(payload)
    parser_wall = time.perf_counter() - start
    # Include the final scheduled render in CPU and memory measurements.
    time.sleep(.08)
    return dict(bytes=len(payload), parser_wall_s=parser_wall,
                mib_per_s=len(payload) / (1024 ** 2) / parser_wall,
                settled_wall_s=time.perf_counter() - start,
                terminal_cpu_s=cpu_seconds(term.process.pid) - t0,
                xvfb_cpu_s=cpu_seconds(server_pid) - x0,
                memory_kib=memory_kib(term.process.pid))


def startup_profile(binary, env, terminal, args):
    phases = {}
    for index in range(args.warmup + args.startup_samples):
        profile_env = dict(env, PROF_T0=repr(time.time() * 1000))
        with terminal([], profile_env, binary) as term:
            time.sleep(.04)
            term.process.terminate()
            term.process.wait(timeout=5)
            term.errors.seek(0)
            seen = {}
            for line in term.errors.read().decode().splitlines():
                if not line.startswith('PROF ') or index < args.warmup:
                    continue
                phase, stamp = line[5:].split('\t')
                seen[phase] = seen.get(phase, 0) + 1
                key = phase + (f' #{seen[phase]}' if seen[phase] > 1 else '')
                phases.setdefault(key, []).append(float(stamp))
    return phases


def run(args, directory, report):
    font_args = ['-fn', args.font]
    common = ['-geometry', '120x40', '-sl', '1000']
    chunks = {
        'ascii': (b'abcdefghijklmnopqrstuvwxyz0123456789 ' * 3 + b'\r\n') * 256,
        'ansi': (b'\x1b[31mred\x1b[0m \x1b[1;32mbold-green\x1b[0m ' * 4 + b'\r\n') * 256,
        'unicode': (('Gr\u00fc\u00dfe caf\u00e9 \u4e16\u754c e\u0301 ' * 6 + '\r\n').encode()) * 256,
    }
    with isolated_display(directory, args.xvfb_cpu) as (env, server_pid):
        def terminal(extra=(), environment=env, binary=args.binary):
            return Terminal(binary, environment, [*common, *font_args, *extra],
                            args.cpu, directory)

        # Use small balanced blocks instead of running all samples of one
        # configuration first. This reduces drift in font comparisons.
        startup = {'default-fixed': [], 'xft': []}
        exit_times = {'default-fixed': [], 'xft': []}
        startup_cpu = {'default-fixed': [], 'xft': []}
        for index in range(args.warmup + args.startup_samples):
            names = list(startup)
            random.Random(args.seed + index).shuffle(names)
            for name in names:
                extra = ['-fn', 'fixed'] if name == 'default-fixed' else []
                with terminal(extra) as term:
                    if index >= args.warmup:
                        startup[name].append(term.ready_ms)
                        startup_cpu[name].append(cpu_seconds(term.process.pid) * 1000)
                start = time.perf_counter()
                proc = spawn([str(args.binary), *common, *font_args, *extra, '-e', '/bin/true'],
                             args.cpu, env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                _, errors = proc.communicate(timeout=30)
                if proc.returncode:
                    raise RuntimeError(errors.decode(errors='replace'))
                if index >= args.warmup:
                    exit_times[name].append((time.perf_counter() - start) * 1000)
        report['startup'] = {name: dict(parser_ready_ms=startup[name],
                                        terminal_cpu_ms=startup_cpu[name],
                                        start_and_exit_ms=exit_times[name]) for name in startup}
        print('Startup median (ms):', {n: round(statistics.median(v), 3)
                                       for n, v in startup.items()}, flush=True)

        if args.profile_binary:
            report['startup_phases_ms'] = startup_profile(args.profile_binary, env, terminal, args)

        if args.plugins:
            target = directory / 'plugins/urxvt/plugins'
            target.mkdir(parents=True)
            for source in args.plugins.glob('*.lua'):
                shutil.copy2(source, target / source.name)
            report['plugin_files'] = sorted(p.name for p in target.iterdir())
            penv = dict(env, XDG_CONFIG_HOME=str(directory / 'plugins'))
            report['plugin_startup'] = []
            for index in range(args.warmup + args.startup_samples):
                with terminal(environment=penv) as term:
                    if index >= args.warmup:
                        report['plugin_startup'].append(dict(parser_ready_ms=term.ready_ms,
                                                             memory_kib=memory_kib(term.process.pid)))

        for name, extra in [('fixed', ['-fn', 'fixed']), ('xft', [])]:
            report['idle'][name] = []
            with terminal(extra) as term:
                time.sleep(.2)
                for _ in range(args.repeats):
                    t0, x0, start = cpu_seconds(term.process.pid), cpu_seconds(server_pid), time.perf_counter()
                    time.sleep(args.idle_seconds)
                    report['idle'][name].append(dict(wall_s=time.perf_counter() - start,
                        terminal_cpu_s=cpu_seconds(term.process.pid) - t0,
                        xvfb_cpu_s=cpu_seconds(server_pid) - x0, memory_kib=memory_kib(term.process.pid)))
            print('Idle complete:', name, flush=True)

        jobs = [(name, scroll) for name in chunks for scroll in (1000, 0)] * args.repeats
        random.Random(args.seed).shuffle(jobs)
        for name, scroll in jobs:
            key = name + '-scroll-' + str(scroll)
            chunk = chunks[name]
            # Keep complete UTF-8 sequences and escape sequences at the end.
            payload = chunk * max(1, args.mib * 1024 ** 2 // len(chunk))
            with terminal(['-sl', str(scroll)]) as term:
                term.send(chunk)
                time.sleep(.08)
                sample = measured_workload(term, server_pid, payload)
            report['throughput'].setdefault(key, []).append(sample)
            print(f'{key}: {sample["mib_per_s"]:.1f} MiB/s, '
                  f'{sample["terminal_cpu_s"]:.3f}s terminal CPU', flush=True)

        # Fill scrollback before sampling memory; idle alone misses the
        # allocations for history that has not yet been used.
        for scroll in (0, 1000, 10000):
            with terminal(['-sl', str(scroll)]) as term:
                before = memory_kib(term.process.pid)
                term.send((b'x' * 119 + b'\r\n') * (scroll + 100))
                time.sleep(.08)
                report['memory'][str(scroll)] = dict(initial_kib=before,
                                                     filled_kib=memory_kib(term.process.pid))

        # Exercise sustained screen updates using each binary's defaults so
        # the same workload also runs on upstream urxvt releases.
        for _ in range(args.repeats):
            with terminal(['-geometry', '240x80']) as term:
                time.sleep(.1)
                start, t0, x0 = time.perf_counter(), cpu_seconds(term.process.pid), cpu_seconds(server_pid)
                frames = math.ceil(args.paced_seconds * 60)
                for index in range(frames):
                    # Alternate all glyphs so every frame actually changes.
                    glyph = b'a' if index % 2 else b'b'
                    term.send(b'\x1b[H' + (glyph * 239 + b'\r\n') * 79)
                    delay = start + (index + 1) / 60 - time.perf_counter()
                    if delay > 0:
                        time.sleep(delay)
                time.sleep(.08)
                sample = dict(wall_s=time.perf_counter() - start,
                              terminal_cpu_s=cpu_seconds(term.process.pid) - t0,
                              xvfb_cpu_s=cpu_seconds(server_pid) - x0,
                              memory_kib=memory_kib(term.process.pid), submitted_frames=frames)
            report['paced'].setdefault('default', []).append(sample)
            print('Paced:', f'{sample["terminal_cpu_s"]:.3f}s terminal CPU, '
                  f'{sample["xvfb_cpu_s"]:.3f}s Xvfb CPU', flush=True)

        if args.perf:
            for name, chunk in chunks.items():
                with terminal() as term, (directory / f'perf-{name}.log').open('w') as log:
                    recorder = subprocess.Popen(['perf', 'record', '-e', 'cycles:u', '-F', '199', '-g', '--call-graph',
                        'dwarf,8192', '-p', str(term.process.pid), '-o', str(directory / f'perf-{name}.data')],
                        stdout=log, stderr=log)
                    try:
                        time.sleep(.2)
                        start = time.monotonic()
                        while recorder.poll() is None and time.monotonic() - start < args.perf_seconds:
                            term.send(chunk * 128)
                    finally:
                        if recorder.poll() is None:
                            recorder.terminate()
                        recorder.wait(timeout=10)
                    report.setdefault('perf_exit_codes', {})[name] = recorder.returncode
                # Sampling permissions can be stricter than counter access.
                # Keep the completed resource benchmarks if perf is unavailable.
                data = directory / f'perf-{name}.data'
                if recorder.returncode not in (0, -15) or not data.exists() or not data.stat().st_size:
                    print(f'Optional perf sampling unavailable; see {directory / ("perf-" + name + ".log")}', flush=True)
                    break
                with (directory / f'perf-{name}.txt').open('w') as output:
                    subprocess.run(['perf', 'report', '--stdio', '--no-children', '--percent-limit', '1',
                                    '-i', str(directory / f'perf-{name}.data')],
                                   stdout=output, stderr=subprocess.STDOUT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', nargs='?', type=Path, default=Path('build/src/nrxvt'))
    parser.add_argument('--output-dir', type=Path, help='keep JSON, metadata and optional perf recordings here')
    parser.add_argument('--cpu', type=int, default=0, help='terminal CPU (default: 0)')
    parser.add_argument('--xvfb-cpu', type=int, default=2, help='X server CPU (default: 2)')
    parser.add_argument('--driver-cpu', type=int, default=4, help='workload producer CPU (default: 4)')
    parser.add_argument('--font', default='xft:monospace:size=11')
    parser.add_argument('--startup-samples', type=positive, default=50)
    parser.add_argument('--warmup', type=positive, default=5)
    parser.add_argument('--repeats', type=positive, default=3)
    parser.add_argument('--idle-seconds', type=duration, default=3)
    parser.add_argument('--mib', type=positive, default=16)
    parser.add_argument('--paced-seconds', type=duration, default=3)
    parser.add_argument('--seed', type=int, default=123)
    parser.add_argument('--plugins', type=Path, help='also measure startup with *.lua files from this directory')
    parser.add_argument('--profile-binary', type=Path, help='optional binary instrumented by dev.py profile-startup')
    parser.add_argument('--perf', action='store_true', help='also sample unmodified terminal CPU hotspots')
    parser.add_argument('--perf-seconds', type=duration, default=3)
    args = parser.parse_args()
    if platform.system() != 'Linux':
        parser.error('this benchmark requires Linux /proc and CPU affinity support')
    for program in ['Xvfb', *(['perf'] if args.perf else [])]:
        if shutil.which(program) is None:
            parser.error(f'{program} is required')
    allowed = os.sched_getaffinity(0)
    cpus = [args.cpu, args.xvfb_cpu, args.driver_cpu]
    if len(set(cpus)) != 3 or not set(cpus) <= allowed:
        parser.error(f'choose three different available CPUs from {sorted(allowed)}')
    # Logical CPU numbers vary by host. Reject siblings so the producer and X
    # server cannot compete with the terminal for the same physical core.
    cores = [(read_optional(f'/sys/devices/system/cpu/cpu{cpu}/topology/physical_package_id'),
              read_optional(f'/sys/devices/system/cpu/cpu{cpu}/topology/core_id')) for cpu in cpus]
    if all(None not in core for core in cores) and len(set(cores)) != 3:
        parser.error('choose CPUs on three separate physical cores')
    args.binary = args.binary.resolve(strict=True)
    if args.profile_binary:
        args.profile_binary = args.profile_binary.resolve(strict=True)
    if args.plugins and not args.plugins.is_dir():
        parser.error('--plugins must name a directory')
    directory = args.output_dir or Path(tempfile.mkdtemp(prefix='urxvt-benchmark-'))
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if (directory / 'results.json').exists():
        parser.error('output directory already contains results.json; use a new directory')
    report = dict(metadata=dict(binary=str(args.binary), binary_sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(),
        benchmark_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        timestamp_utc=datetime.now(timezone.utc).isoformat(), platform=platform.platform(),
        cpu_model=next((line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines()
                        if line.startswith('model name')), None),
        arguments={key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
        cpu_topology={str(cpu): {name: read_optional(f'/sys/devices/system/cpu/cpu{cpu}/topology/{name}')
                                 for name in ('physical_package_id', 'core_id', 'thread_siblings_list')}
                      for cpu in cpus},
        loadavg_start=read_optional('/proc/loadavg'), cpuinfo=read_optional('/proc/cpuinfo'),
        power={str(cpu): {name: read_optional(f'/sys/devices/system/cpu/cpu{cpu}/cpufreq/{name}')
                         for name in ('scaling_governor', 'energy_performance_preference', 'scaling_min_freq', 'scaling_max_freq')}
               for cpu in cpus},
        turbo_disabled=read_optional('/sys/devices/system/cpu/intel_pstate/no_turbo')),
        idle={}, throughput={}, memory={}, paced={})
    options = args.binary.parent.parent / 'meson-info/intro-buildoptions.json'
    if options.exists():
        report['metadata']['build_options'] = json.loads(options.read_text())
    if args.profile_binary:
        report['metadata']['profile_binary_sha256'] = hashlib.sha256(args.profile_binary.read_bytes()).hexdigest()
    print(f'Artifacts: {directory}\nCPU affinity: terminal={args.cpu}, Xvfb={args.xvfb_cpu}, driver={args.driver_cpu}', flush=True)
    try:
        with affinity(args.driver_cpu):
            run(args, directory, report)
        report['metadata']['binary_sha256_after'] = hashlib.sha256(args.binary.read_bytes()).hexdigest()
        if report['metadata']['binary_sha256_after'] != report['metadata']['binary_sha256']:
            raise RuntimeError('executable changed during the benchmark; discard this run')
        report['completed'] = True
    finally:
        # Preserve partial results on failure, explicitly marked incomplete.
        report.setdefault('completed', False)
        report['metadata']['loadavg_end'] = read_optional('/proc/loadavg')
        (directory / 'results.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
