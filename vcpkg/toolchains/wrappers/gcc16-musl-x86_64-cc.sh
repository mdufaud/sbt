#!/bin/sh
# Fix: GCC 16 injects -latomic_asneeded via link_gcc_c_sequence spec
# (%{!fno-link-libatomic:-latomic_asneeded}) but the musl sysroot does not
# ship libatomic_asneeded, causing all link steps to fail.
exec x86_64-linux-musl-gcc -fno-link-libatomic "$@"
