#!/bin/bash
# Build a specific SQLite version as a shared library that Python's
# sqlite3 module can load in place of the system one (Linux only).
#
# Usage: scripts/build-sqlite.sh [output-directory]
#
# Then run Python with LD_LIBRARY_PATH set to the output directory:
#
#   scripts/build-sqlite.sh /tmp/sqlite
#   LD_LIBRARY_PATH=/tmp/sqlite python -c 'import sqlite3; print(sqlite3.sqlite_version)'
#
# This only works for Python builds that load libsqlite3.so.0 dynamically,
# such as the ones installed by actions/setup-python or a Linux distribution.
# It has no effect on builds that link SQLite statically, such as uv's.
#
# To build a different version set SQLITE_VERSION. The source comes from
# the matching version-X.Y.Z tag of https://github.com/sqlite/sqlite
set -euo pipefail

SQLITE_VERSION="${SQLITE_VERSION:-3.54.1}"
output_dir="${1:-sqlite-build}"

mkdir -p "$output_dir"
output_dir="$(cd "$output_dir" && pwd)"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
cd "$work_dir"

git -c advice.detachedHead=false clone --quiet --depth 1 \
    --branch "version-$SQLITE_VERSION" \
    https://github.com/sqlite/sqlite.git sqlite
cd sqlite

# Generate the sqlite3.c amalgamation, then compile it with the options
# we want. This uses the bundled jimsh so Tcl does not need to be installed.
./configure > /dev/null
make sqlite3.c > /dev/null

gcc -O2 -fPIC -shared \
    -DSQLITE_ENABLE_COLUMN_METADATA \
    -DSQLITE_ENABLE_FTS3 \
    -DSQLITE_ENABLE_FTS3_PARENTHESIS \
    -DSQLITE_ENABLE_FTS4 \
    -DSQLITE_ENABLE_FTS5 \
    -DSQLITE_ENABLE_LOAD_EXTENSION \
    -DSQLITE_ENABLE_MATH_FUNCTIONS \
    -DSQLITE_ENABLE_RTREE \
    sqlite3.c \
    -Wl,-soname,libsqlite3.so.0 \
    -o "$output_dir/libsqlite3.so.0" \
    -lpthread -ldl -lm

echo "Built SQLite $SQLITE_VERSION at $output_dir/libsqlite3.so.0"
