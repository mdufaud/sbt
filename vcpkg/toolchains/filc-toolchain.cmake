cmake_minimum_required(VERSION 3.10)

# Fil-C toolchain: a clang fork carrying its own sysroot (the "pizfix": musl
# libc, libc++/libc++abi, libpizlo runtime). The driver finds the pizfix from
# its own location, so no sysroot/target flags are needed here.
# FILC_PATH is exported into the vcpkg environment by sbt/vcpkg/install.py.

set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR x86_64)

set(FILC_ROOT "$ENV{FILC_PATH}")

set(CMAKE_C_COMPILER "${FILC_ROOT}/build/bin/clang")
set(CMAKE_CXX_COMPILER "${FILC_ROOT}/build/bin/clang++")

# Fil-C ships no llvm-ar/llvm-ranlib; host binutils read its ELF objects fine.
set(CMAKE_AR "ar" CACHE FILEPATH "Archiver")
set(CMAKE_RANLIB "ranlib" CACHE FILEPATH "Ranlib")

# Keep find_* off the host glibc tree: nothing there can link into a pizfix binary.
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)

# For non-CMake ports, vcpkg reads these directly.
set(VCPKG_C_COMPILER "${CMAKE_C_COMPILER}")
set(VCPKG_CXX_COMPILER "${CMAKE_CXX_COMPILER}")
set(VCPKG_C_COMPILER_ID Clang)
set(VCPKG_CXX_COMPILER_ID Clang)
