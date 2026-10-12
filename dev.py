#!/usr/bin/env python3
# Development helper for building, running and installing rxvt-unicode.
#
# Wraps the meson build (in ./build), so the usual steps are available as
# subcommands:
#
#   ./dev.py configure [--prefix DIR] [-- MESON_ARGS...]
#   ./dev.py build [-j N]
#   ./dev.py run [-- RXVT_ARGS...]
#   ./dev.py install [--destdir DIR]
#   ./dev.py clean [--dist]
#
# REQUIRES: python meson ninja pkg-config libptytty
import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys

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


def cmd_configure(args):
    configure(args.prefix, args.meson_args)


def cmd_build(args):
    ensure_configured()
    compile_(args.jobs)


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
        description="Build, run and install rxvt-unicode for development"
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
