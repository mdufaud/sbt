#!/bin/sh
# -fPIC for every port: CMake ports honor the triplet's CMAKE_C_FLAGS, but
# autotools/meson ports (e.g. util-linux/libuuid) ignore it, producing non-PIC
# .a archives that fail to link into a shared module (R_X86_64_32). Forcing it
# in the universal CC wrapper covers every port uniformly (harmless for static).
if [ -n "${ZIG_TARGET:-}" ]; then
    exec zig cc -target "$ZIG_TARGET" -fPIC "$@"
fi
exec zig cc -fPIC "$@"
