#!/usr/bin/env python3
# Development helper for building, testing, running and installing rxvt-unicode.
#
# Wraps the meson build (in ./build), so the usual steps are available as
# subcommands:
#
#   ./dev.py configure [--prefix DIR] [-- MESON_ARGS...]
#   ./dev.py build [-j N]
#   ./dev.py test [-j N]
#   ./dev.py run [-- RXVT_ARGS...]
#   ./dev.py install [--destdir DIR]
#   ./dev.py clean [--dist]
#   ./dev.py profile-startup [-n RUNS] [-- RXVT_ARGS...]
#
# REQUIRES: python meson ninja pkg-config libptytty
import argparse
import collections
import json
import os
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import time

# Every path is resolved relative to the repository root, so the script works
# no matter which directory it is invoked from.
ROOT = os.path.dirname(os.path.realpath(__file__))

BUILD_DIR = os.path.join(ROOT, "build")

# Installing into the user's home avoids needing root for a development build.
DEFAULT_PREFIX = os.path.expanduser("~/.local")


def run(cmd, **kwargs):
    """Echo and run `cmd` in the repository root, exiting on failure."""
    print(f"+ {shlex.join(cmd)}", flush=True)
    try:
        subprocess.run(cmd, cwd=ROOT, check=True, **kwargs)
    except subprocess.CalledProcessError as error:
        # The tool has already printed the actual cause, so only report which
        # step failed instead of dumping a Python traceback.
        print(
            f"Command failed with status {error.returncode}: {shlex.join(cmd)}",
            file=sys.stderr,
        )
        raise SystemExit(error.returncode) from None


def is_configured():
    return os.path.exists(os.path.join(BUILD_DIR, "build.ninja"))


def configure(prefix=DEFAULT_PREFIX, extra_args=()):
    cmd = ["meson", "setup", BUILD_DIR, f"--prefix={prefix}", *extra_args]
    # Re-running setup on an existing build directory needs --reconfigure,
    # which keeps all options that are not given again.
    if is_configured():
        cmd.insert(2, "--reconfigure")
    run(cmd)


def ensure_configured():
    """Configure with defaults unless a previous configure run exists."""
    if not is_configured():
        configure()


def compile_(jobs=None):
    cmd = ["meson", "compile", "-C", BUILD_DIR]
    if jobs:
        cmd.append(f"-j{jobs}")
    run(cmd)


def build_option(name):
    """Look up the value of a meson option of the configured build."""
    intro = os.path.join(BUILD_DIR, "meson-info", "intro-buildoptions.json")
    with open(intro) as f:
        options = json.load(f)
    return next(option["value"] for option in options if option["name"] == name)


def user_options():
    """Return the project options of the configured build as -D arguments."""
    intro = os.path.join(BUILD_DIR, "meson-info", "intro-buildoptions.json")
    with open(intro) as f:
        options = json.load(f)
    result = []
    for option in options:
        if option["section"] != "user":
            continue
        value = option["value"]
        if isinstance(value, bool):
            value = "true" if value else "false"
        elif isinstance(value, list):
            value = ",".join(value)
        result.append(f"-D{option['name']}={value}")
    return result


# --- startup profiling -------------------------------------------------------
#
# The profiled binary is built from a copy of the working tree with timestamp
# calls patched in, so the real sources stay free of profiling code (and of
# conflicts with upstream). Both the copy and its build live below ./build.

PROFILE_DIR = os.path.join(BUILD_DIR, "profile")
PROFILE_SRC = os.path.join(PROFILE_DIR, "src")
PROFILE_BUILD = os.path.join(PROFILE_DIR, "build")

# Prints "PROF <phase> <ms>" to stderr, measured from PROF_T0 (wall clock ms
# taken by dev.py right before spawning urxvt), so process startup and dynamic
# linking are included in the first phase.
PROFILE_HELPER = r"""
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
// startup profiling, patched in by dev.py profile-startup
static inline void prof (const char *what)
{
  static double t0 = -1;
  struct timespec ts;
  clock_gettime (CLOCK_REALTIME, &ts);
  double now = ts.tv_sec * 1e3 + ts.tv_nsec / 1e6;
  if (t0 < 0)
    {
      const char *env = getenv ("PROF_T0");
      t0 = env ? atof (env) : now;
    }
  fprintf (stderr, "PROF %s\t%.3f\n", what, now - t0);
}
"""

# {file: [(anchor, replacement)]}, each anchor has to match exactly once.
PROFILE_PATCHES = {
    "src/rxvt.h": [
        ('#include "feature.h"\n', '#include "feature.h"\n' + PROFILE_HELPER),
    ],
    "src/rxvt.C": [
        (
            "    rxvt_init ();\n",
            '    prof ("main");\n    rxvt_init ();\n    prof ("rxvt_init");\n',
        ),
        (
            "    t->init (argc, argv, environ);\n",
            '    t->init (argc, argv, environ);\n    prof ("init done");\n',
        ),
    ],
    "src/init.C": [
        ("  init_vars ();\n", '  init_vars ();\n  prof ("init_vars");\n'),
        (
            "  const char **cmd_argv = init_resources (argc, argv);\n",
            "  const char **cmd_argv = init_resources (argc, argv);\n"
            '  prof ("init_resources");\n',
        ),
        (
            "  if (!set_fonts ())",
            '  prof ("create_windows (pre fonts)");\n'
            "  bool prof_fonts_ok = set_fonts ();\n"
            '  prof ("set_fonts");\n'
            "  if (!prof_fonts_ok)",
        ),
        (
            "  create_windows (argc, argv);\n",
            '  create_windows (argc, argv);\n  prof ("create_windows");\n',
        ),
        (
            "  init_xlocale ();\n",
            '  init_xlocale ();\n  prof ("init_xlocale (XIM)");\n',
        ),
        (
            "  scr_poweron (); // initialize screen\n",
            '  scr_poweron (); // initialize screen\n  prof ("scr_poweron");\n',
        ),
        (
            "  init_command (cmd_argv);\n",
            '  init_command (cmd_argv);\n  prof ("init_command (pty+fork)");\n',
        ),
    ],
    "src/rxvtfont.C": [
        (
            "  FcPattern *p = FcNameParse ((FcChar8 *) name);\n",
            '  prof ("xft load start");\n'
            "  FcPattern *p = FcNameParse ((FcChar8 *) name);\n",
        ),
        (
            "  FcPatternDestroy (p);\n\n  if (!match)",
            '  prof ("XftFontMatch");\n  FcPatternDestroy (p);\n\n  if (!match)',
        ),
        (
            "      FT_Face face = XftLockFace (f);\n",
            '      prof ("XftFontOpenPattern");\n'
            "      FT_Face face = XftLockFace (f);\n",
        ),
    ],
    "src/screen.C": [
        # Time stamps the end of the first two refreshes (the first one is
        # the initial draw, the second one usually shows the shell prompt).
        (
            "rxvt_term::scr_refresh () noexcept\n{\n",
            "rxvt_term::scr_refresh () noexcept\n{\n"
            "  static int prof_n;\n"
            "  struct prof_end { ~prof_end () { if (prof_n++ < 2) "
            'prof ("scr_refresh"); } } prof_end_;\n',
        ),
    ],
}


def patch_source(path, content):
    """Apply the profiling patches for `path` (relative to ROOT) to `content`."""
    for anchor, replacement in PROFILE_PATCHES.get(path, ()):
        count = content.count(anchor)
        if count != 1:
            raise SystemExit(
                f"profile-startup: expected the anchor once in {path}, found it "
                f"{count} times, update PROFILE_PATCHES in dev.py:\n{anchor}"
            )
        content = content.replace(anchor, replacement)
    return content


def sync_profile_tree():
    """Mirror the working tree (tracked and untracked, not ignored files) into
    PROFILE_SRC with the profiling patches applied.

    Files are only rewritten when their content changes, so the instrumented
    build stays incremental.
    """
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode()
    wanted = set()
    for path in filter(None, listing.split("\0")):
        src = os.path.join(ROOT, path)
        dst = os.path.join(PROFILE_SRC, path)
        # Tracked but deleted in the working tree.
        if not os.path.lexists(src):
            continue
        wanted.add(path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.islink(src):
            # Keep symlinks as they are.
            target = os.readlink(src)
            if os.path.islink(dst) and os.readlink(dst) == target:
                continue
            if os.path.lexists(dst):
                os.remove(dst)
            os.symlink(target, dst)
            continue
        with open(src, "rb") as f:
            data = f.read()
        if path in PROFILE_PATCHES:
            data = patch_source(path, data.decode()).encode()
        if os.path.isfile(dst) and not os.path.islink(dst):
            with open(dst, "rb") as f:
                if f.read() == data:
                    continue
        if os.path.lexists(dst):
            os.remove(dst)
        with open(dst, "wb") as f:
            f.write(data)
        shutil.copymode(src, dst)
    # Drop files that disappeared from the working tree.
    for dirpath, _, filenames in os.walk(PROFILE_SRC):
        for name in filenames:
            path = os.path.relpath(os.path.join(dirpath, name), PROFILE_SRC)
            if path not in wanted:
                os.remove(os.path.join(dirpath, name))


def build_profile_binary(jobs=None):
    """Build the instrumented urxvt with the options of ./build."""
    sync_profile_tree()
    cmd = ["meson", "setup", PROFILE_BUILD, PROFILE_SRC, *user_options()]
    if os.path.exists(os.path.join(PROFILE_BUILD, "build.ninja")):
        reconfigure = [*cmd[:2], "--reconfigure", *cmd[2:]]
        print(f"+ {shlex.join(reconfigure)}", flush=True)
        result = subprocess.run(reconfigure, cwd=ROOT, capture_output=True, text=True)
        if result.returncode == 0:
            cmd = None
        else:
            # Reconfiguring rejects options that were added to meson.options
            # since the last setup, so start over with a fresh build.
            print("Reconfiguring failed, setting up the profile build from scratch.")
            shutil.rmtree(PROFILE_BUILD)
    if cmd:
        run(cmd, stdout=subprocess.DEVNULL)
    cmd = ["meson", "compile", "-C", PROFILE_BUILD]
    if jobs:
        cmd.append(f"-j{jobs}")
    run(cmd, stdout=subprocess.DEVNULL)
    return os.path.join(PROFILE_BUILD, "src", build_option("name"))


def profile_run(cmd):
    """Run `cmd` once, returning its phase timestamps and the total wall time."""
    env = dict(os.environ)
    t0 = time.time() * 1e3
    env["PROF_T0"] = repr(t0)
    proc = subprocess.run(
        cmd, env=env, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
    )
    total = time.time() * 1e3 - t0
    phases = []
    other = []
    seen = collections.Counter()
    for line in proc.stderr.splitlines():
        match = re.fullmatch(r"PROF (.+)\t([\d.]+)", line)
        if not match:
            other.append(line)
            continue
        # Phases can be hit more than once (e.g. one font load per style).
        name = match.group(1)
        seen[name] += 1
        if seen[name] > 1:
            name = f"{name} #{seen[name]}"
        phases.append((name, float(match.group(2))))
    if proc.returncode != 0:
        print("\n".join(other), file=sys.stderr)
        raise SystemExit(
            f"profile-startup: {shlex.join(cmd)} exited with status {proc.returncode}"
        )
    return phases, total


def format_stats(values):
    return (
        f"{statistics.median(values):7.1f} ms"
        f"  (mean {statistics.mean(values):5.1f}, "
        f"min {min(values):5.1f}, max {max(values):5.1f})"
    )


def cmd_profile_startup(args):
    ensure_configured()
    compile_(args.jobs)
    binary = build_profile_binary(args.jobs)
    # '-e true' exits right after startup, so each run measures exactly one
    # start, unless the caller asks for another command.
    rxvt_args = args.rxvt_args or ["-e", "true"]
    cmd = [binary, *rxvt_args]
    print(f"+ {shlex.join(cmd)}  ({args.warmup} warmup, {args.runs} runs)", flush=True)

    for _ in range(args.warmup):
        profile_run(cmd)
    samples = collections.defaultdict(list)
    order = {}
    totals = []
    for _ in range(args.runs):
        phases, total = profile_run(cmd)
        totals.append(total)
        for name, stamp in phases:
            samples[name].append(stamp)
            order.setdefault(name, len(order))

    # Phases are sorted by their median timestamp, the delta shows how long
    # the step since the previous phase took.
    print(f"\n{'phase':34s} {'at':>9s} {'delta':>8s}")
    previous = 0.0
    for name in sorted(samples, key=lambda n: (statistics.median(samples[n]), order[n])):
        at = statistics.median(samples[name])
        print(f"{name:34s} {at:7.1f} ms {at - previous:+6.1f}")
        previous = at
    at = statistics.median(totals)
    print(f"{'process exit':34s} {at:7.1f} ms {at - previous:+6.1f}")

    # End to end time of the uninstrumented binary (no stderr output, no
    # timestamp overhead), which is the number that actually matters.
    plain = os.path.join(BUILD_DIR, "src", build_option("name"))
    plain_totals = [profile_run([plain, *rxvt_args])[1] for _ in range(args.runs)]
    print(f"\n{'instrumented total':20s} {format_stats(totals)}")
    print(f"{'plain build total':20s} {format_stats(plain_totals)}")


def cmd_configure(args):
    configure(args.prefix, args.meson_args)


def cmd_build(args):
    ensure_configured()
    compile_(args.jobs)


def cmd_test(args):
    ensure_configured()
    compile_(args.jobs)
    binary = os.path.join(BUILD_DIR, "src", build_option("name"))
    # Run timing-sensitive harnesses sequentially against the same fresh build.
    for script in ("rendering.py", "refresh-rate.py", "latency.py"):
        run([sys.executable, "-u", os.path.join(ROOT, "tests", script), binary])


def cmd_run(args):
    ensure_configured()
    compile_(args.jobs)

    # The binary is named after the 'name' option (urxvt by default).
    binary = os.path.join(BUILD_DIR, "src", build_option("name"))
    print(f"+ {shlex.join([binary, *args.rxvt_args])}", flush=True)
    # Replace this process, so signals and the exit status pass straight
    # through to the terminal.
    os.execv(binary, [binary, *args.rxvt_args])


def cmd_install(args):
    ensure_configured()
    compile_(args.jobs)
    cmd = ["meson", "install", "-C", BUILD_DIR, "--no-rebuild"]
    if args.destdir:
        # DESTDIR stages the install below a directory (e.g. for packaging)
        # while keeping the configured prefix in the installed files.
        cmd.append(f"--destdir={os.path.abspath(args.destdir)}")
    run(cmd)


def cmd_clean(args):
    if not is_configured():
        print("Not configured, nothing to clean.")
        return
    if args.dist:
        # Dropping the build directory also drops the configured options,
        # forcing a fresh configure on the next build.
        print(f"+ rm -rf {shlex.quote(BUILD_DIR)}", flush=True)
        shutil.rmtree(BUILD_DIR)
    else:
        run(["meson", "compile", "-C", BUILD_DIR, "--clean"])


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Build, test, run and install rxvt-unicode for development"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Shared by every subcommand that compiles something.
    jobs_parser = argparse.ArgumentParser(add_help=False)
    jobs_parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        help="number of parallel build jobs (default: ninja's choice)",
    )

    p = sub.add_parser("configure", help="set up or reconfigure ./build")
    p.add_argument(
        "--prefix",
        default=DEFAULT_PREFIX,
        help="installation prefix (default: %(default)s)",
    )
    p.add_argument(
        "meson_args",
        nargs=argparse.REMAINDER,
        help="extra arguments passed to 'meson setup' (e.g. -Dxft=disabled), after '--'",
    )
    p.set_defaults(func=cmd_configure)

    p = sub.add_parser(
        "build", parents=[jobs_parser], help="build, configuring first if needed"
    )
    p.set_defaults(func=cmd_build)

    p = sub.add_parser(
        "test", parents=[jobs_parser], help="build and run all test harnesses"
    )
    p.set_defaults(func=cmd_test)

    p = sub.add_parser(
        "run", parents=[jobs_parser], help="build and run the freshly built urxvt"
    )
    p.add_argument(
        "rxvt_args",
        nargs=argparse.REMAINDER,
        help="arguments passed to urxvt, after '--'",
    )
    p.set_defaults(func=cmd_run)

    p = sub.add_parser(
        "install", parents=[jobs_parser], help="build and install into the prefix"
    )
    p.add_argument("--destdir", help="stage the installation below this directory")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("clean", help="remove build artifacts")
    p.add_argument(
        "--dist",
        action="store_true",
        help="remove the whole build directory, including its configuration",
    )
    p.set_defaults(func=cmd_clean)

    p = sub.add_parser(
        "profile-startup",
        parents=[jobs_parser],
        help="time the startup phases of an instrumented urxvt build",
    )
    p.add_argument(
        "-n",
        "--runs",
        type=int,
        default=20,
        help="number of measured runs (default: %(default)s)",
    )
    p.add_argument(
        "-w",
        "--warmup",
        type=int,
        default=3,
        help="number of unmeasured warmup runs (default: %(default)s)",
    )
    p.add_argument(
        "rxvt_args",
        nargs=argparse.REMAINDER,
        help="arguments passed to urxvt instead of '-e true', after '--'",
    )
    p.set_defaults(func=cmd_profile_startup)

    args = parser.parse_args(argv)

    # REMAINDER keeps the '--' separator, which neither tool expects.
    for name in ("meson_args", "rxvt_args"):
        rest = getattr(args, name, None)
        if rest and rest[0] == "--":
            del rest[0]

    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
