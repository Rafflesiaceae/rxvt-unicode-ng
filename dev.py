#!/usr/bin/env python3
# Development helper for building, running and installing rxvt-unicode.
#
# Wraps the autoconf based build (autogen.sh, configure, make), so the usual
# steps are available as subcommands:
#
#   ./dev.py configure [--prefix DIR] [-- CONFIGURE_ARGS...]
#   ./dev.py build [-j N]
#   ./dev.py run [-- RXVT_ARGS...]
#   ./dev.py install [--destdir DIR]
#   ./dev.py clean [--dist]
#
# REQUIRES: python autoconf make pkg-config libptytty
import argparse
import os
import shlex
import subprocess
import sys

# Every path is resolved relative to the repository root, so the script works
# no matter which directory it is invoked from.
ROOT = os.path.dirname(os.path.realpath(__file__))

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


def path(*parts):
    return os.path.join(ROOT, *parts)


def is_configured():
    return os.path.exists(path("Makefile")) and os.path.exists(path("config.status"))


def ensure_libev():
    """Fail early with a hint when the vendored libev checkout is missing."""
    if not os.path.exists(path("libev", "ev++.h")):
        print(
            "libev/ is missing, run './vendor.py' to fetch the vendored copy.",
            file=sys.stderr,
        )
        raise SystemExit(1)


def configure(prefix=DEFAULT_PREFIX, extra_args=()):
    ensure_libev()
    # `configure` is checked in, so it is only generated when missing. Going
    # by mtimes would rewrite the tracked file after every fresh checkout, as
    # git does not preserve them.
    if not os.path.exists(path("configure")):
        run(["./autogen.sh"])
    run(["./configure", f"--prefix={prefix}", *extra_args])


def ensure_configured():
    """Configure with defaults unless a previous configure run exists."""
    if not is_configured():
        configure()


def make(*targets, jobs=None):
    cmd = ["make"]
    if jobs:
        cmd.append(f"-j{jobs}")
    run(cmd + list(targets))


def cmd_configure(args):
    configure(args.prefix, args.configure_args)


def cmd_build(args):
    ensure_configured()
    make(jobs=args.jobs)


def cmd_run(args):
    ensure_configured()
    make(jobs=args.jobs)
    binary = path("src", "rxvt")

    # The binary looks for urxvt.pm and the extensions below the configured
    # LIBDIR, which only exists after an install. Point perl at the sources
    # instead, so the in-tree build runs with its own perl code.
    env = dict(os.environ)
    for var, src in (("PERL5LIB", path("src")), ("URXVT_PERL_LIB", path("src", "perl"))):
        env[var] = os.pathsep.join(filter(None, [src, env.get(var)]))

    print(f"+ {shlex.join([binary, *args.rxvt_args])}", flush=True)
    # Replace this process, so signals and the exit status pass straight
    # through to the terminal.
    os.execve(binary, [binary, *args.rxvt_args], env)


def cmd_install(args):
    ensure_configured()
    make(jobs=args.jobs)
    targets = ["install"]
    if args.destdir:
        # DESTDIR stages the install below a directory (e.g. for packaging)
        # while keeping the configured prefix in the installed files.
        targets.append(f"DESTDIR={os.path.abspath(args.destdir)}")
    make(*targets)


def cmd_clean(args):
    if not is_configured():
        print("Not configured, nothing to clean.")
        return
    # distclean additionally drops the configure output, forcing a fresh
    # configure on the next build.
    make("distclean" if args.dist else "clean")


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
        default=os.cpu_count(),
        help="number of parallel make jobs (default: %(default)s)",
    )

    p = sub.add_parser("configure", help="(re)run ./configure")
    p.add_argument(
        "--prefix",
        default=DEFAULT_PREFIX,
        help="installation prefix (default: %(default)s)",
    )
    p.add_argument(
        "configure_args",
        nargs=argparse.REMAINDER,
        help="extra arguments passed to ./configure, after '--'",
    )
    p.set_defaults(func=cmd_configure)

    p = sub.add_parser(
        "build", parents=[jobs_parser], help="build, configuring first if needed"
    )
    p.set_defaults(func=cmd_build)

    p = sub.add_parser(
        "run", parents=[jobs_parser], help="build and run the in-tree src/rxvt"
    )
    p.add_argument(
        "rxvt_args",
        nargs=argparse.REMAINDER,
        help="arguments passed to rxvt, after '--'",
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
        help="also remove the configure output (make distclean)",
    )
    p.set_defaults(func=cmd_clean)

    args = parser.parse_args(argv)

    # REMAINDER keeps the '--' separator, which neither tool expects.
    for name in ("configure_args", "rxvt_args"):
        rest = getattr(args, name, None)
        if rest and rest[0] == "--":
            del rest[0]

    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
