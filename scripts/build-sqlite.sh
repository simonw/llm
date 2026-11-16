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
# To build a different version set SQLITE_VERSION, SQLITE_YEAR (the year of
# that release, which is part of the download URL) and SQLITE_SHA3_256 (the
# hash of the amalgamation zip listed on https://sqlite.org/download.html).
set -euo pipefail

SQLITE_VERSION="${SQLITE_VERSION:-3.54.1}"
SQLITE_YEAR="${SQLITE_YEAR:-2026}"
SQLITE_SHA3_256="${SQLITE_SHA3_256:-92281c86e2957f9b9305890f9ac04204caa7b677cc868dc326d942689df28e30}"
output_dir="${1:-sqlite-build}"

# 3.54.1 -> 3540100
IFS=. read -r major minor patch <<< "$SQLITE_VERSION"
name="sqlite-amalgamation-$(printf '%d%02d%02d00' "$major" "$minor" "$patch")"

mkdir -p "$output_dir"
output_dir="$(cd "$output_dir" && pwd)"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
cd "$work_dir"

curl -sSfLO "https://sqlite.org/$SQLITE_YEAR/$name.zip"
actual_hash="$(openssl dgst -sha3-256 -r "$name.zip" | cut -d' ' -f1)"
if [ "$actual_hash" != "$SQLITE_SHA3_256" ]; then
    echo "SHA3-256 mismatch for $name.zip" >&2
    echo "  expected $SQLITE_SHA3_256" >&2
    echo "  actual   $actual_hash" >&2
    exit 1
fi
unzip -q "$name.zip"

gcc -O2 -fPIC -shared \
    -DSQLITE_ENABLE_COLUMN_METADATA \
    -DSQLITE_ENABLE_FTS3 \
    -DSQLITE_ENABLE_FTS3_PARENTHESIS \
    -DSQLITE_ENABLE_FTS4 \
    -DSQLITE_ENABLE_FTS5 \
    -DSQLITE_ENABLE_LOAD_EXTENSION \
    -DSQLITE_ENABLE_MATH_FUNCTIONS \
    -DSQLITE_ENABLE_RTREE \
    "$name/sqlite3.c" \
    -Wl,-soname,libsqlite3.so.0 \
    -o "$output_dir/libsqlite3.so.0" \
    -lpthread -ldl -lm

echo "Built SQLite $SQLITE_VERSION at $output_dir/libsqlite3.so.0"
