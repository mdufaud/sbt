#!/bin/sh
# -fPIC for every port (see zig-cc.sh): autotools/meson ports ignore the
# triplet's CMAKE_CXX_FLAGS, so force PIC here for uniform shared linkage.
if [ -n "${ZIG_TARGET:-}" ]; then
    exec zig c++ -target "$ZIG_TARGET" -fPIC "$@"
fi
exec zig c++ -fPIC "$@"
