#!/bin/sh
# Builds rxvt-unicode-ng the way the CI jobs do. It is kept to plain POSIX sh
# so that it runs unchanged on Linux, macOS, the BSDs and Solaris, where the
# build tools themselves are installed by the workflow beforehand.
#
# libptytty is not packaged everywhere, so it is built from source into a
# private prefix whenever pkg-config cannot find it (or CI_BUILD_LIBPTYTTY=1).
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)
work=${TMPDIR:-/tmp}/rxvt-ci
prefix=$work/prefix
ptytty_version=2.0
ptytty_sha256=8033ed3aadf28759660d4f11f2d7b030acf2a6890cb0f7926fb0cfa6739d31f7

jobs=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)

# The private prefix has to be searched in addition to the system locations.
PKG_CONFIG_PATH=$prefix/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}
export PKG_CONFIG_PATH

# Not every platform ships sha256sum (BSDs have sha256, macOS shasum).
sha256_of () {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d ' ' -f 1
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | cut -d ' ' -f 1
  elif command -v sha256 >/dev/null 2>&1; then
    sha256 -q "$1"
  else
    digest -a sha256 "$1"
  fi
}

build_libptytty () {
  mkdir -p "$work"
  cd "$work"
  tarball=libptytty-$ptytty_version.tar.gz
  curl -fsSL -o "$tarball" "https://dist.schmorp.de/libptytty/$tarball"
  if [ "$(sha256_of "$tarball")" != "$ptytty_sha256" ]; then
    echo "checksum mismatch for $tarball" >&2
    exit 1
  fi
  rm -rf "libptytty-$ptytty_version"
  tar xzf "$tarball"
  # A static library keeps the resulting binary independent of the prefix.
  cmake -S "libptytty-$ptytty_version" -B ptytty-build \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$prefix" \
    -DCMAKE_INSTALL_LIBDIR=lib \
    -DBUILD_SHARED_LIBS=OFF
  cmake --build ptytty-build -j "$jobs"
  cmake --install ptytty-build
  cd "$root"
}

if [ "${CI_BUILD_LIBPTYTTY:-0}" = 1 ] || ! pkg-config --exists libptytty; then
  build_libptytty
fi

cd "$root"
# Start from scratch so a stale checkout cache can never mask a failure.
rm -rf "$work/build" "$work/destdir"
meson setup "$work/build" --prefix=/usr/local
meson compile -C "$work/build" -j "$jobs"
# Installing catches missing files (man pages, lua plugins) as well.
DESTDIR=$work/destdir meson install -C "$work/build"
