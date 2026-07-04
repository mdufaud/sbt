cmake_minimum_required(VERSION 3.0)

set(CMAKE_SYSTEM_NAME Linux)

set(ZIG_CC "${CMAKE_CURRENT_LIST_DIR}/wrappers/zig-cc.sh")
set(ZIG_CXX "${CMAKE_CURRENT_LIST_DIR}/wrappers/zig-cxx.sh")

# --- CMAKE CONFIGURATION ---

# Point CMake to our generated wrappers
set(CMAKE_C_COMPILER "${ZIG_CC}")
set(CMAKE_CXX_COMPILER "${ZIG_CXX}")

# Force static library mode for CMake's internal compiler checks.
# This prevents "linking not supported" errors during the initial setup phase
# because Zig cross-compilation often lacks a dynamic linker for the target system.
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

# Disable CMake's dependency scanning which can confuse Zig
set(CMAKE_C_LINKER_DEPFILE_SUPPORTED FALSE)
set(CMAKE_CXX_LINKER_DEPFILE_SUPPORTED FALSE)

# Cross-compilation root path settings
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)

# --- VCPKG SPECIFIC ---
# For non-CMake ports (like OpenSSL, FFmpeg), vcpkg reads these variables.
# They will now point to our single-file wrapper script, avoiding argument parsing issues.
set(VCPKG_C_COMPILER "${ZIG_CC}")
set(VCPKG_CXX_COMPILER "${ZIG_CXX}")

# Help vcpkg identify the compiler type
set(VCPKG_C_COMPILER_ID Clang)
set(VCPKG_CXX_COMPILER_ID Clang)

# Disable glibc assumptions
set(VCPKG_CMAKE_SYSTEM_VERSION 1)