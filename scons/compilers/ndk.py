"""
Android NDK Clang compiler configuration for SCons.

Resolves NDK toolchain binaries from ANDROID_NDK_PATH and configures
the build environment for cross-compilation to Android targets.
"""

import os

from sbt.core import architectures
from sbt.core import builder
from sbt.core import logger


def load_in_env(env):
    ndk_root = builder.get_ndk_root()
    if not ndk_root:
        raise SystemExit("ANDROID_NDK_PATH is not set")

    toolchain_bin = builder.get_ndk_toolchain_bin()
    if not os.path.isdir(toolchain_bin):
        raise SystemExit(f"NDK toolchain bin not found: {toolchain_bin}")

    api_level = builder.get_ndk_api_level()
    ndk_target = architectures.get_ndk_target(builder.build_machine)
    if not ndk_target:
        raise SystemExit(f"no NDK target for machine: {builder.build_machine}")

    # NDK clang binaries: <target><api>-clang / <target><api>-clang++
    cc = os.path.join(toolchain_bin, f"{ndk_target}{api_level}-clang")
    cxx = os.path.join(toolchain_bin, f"{ndk_target}{api_level}-clang++")
    ar = os.path.join(toolchain_bin, "llvm-ar")
    ranlib = os.path.join(toolchain_bin, "llvm-ranlib")

    # Verify binaries exist
    for name, path in [("CC", cc), ("CXX", cxx), ("AR", ar), ("RANLIB", ranlib)]:
        if not os.path.isfile(path):
            raise SystemExit(f"NDK {name} not found: {path}")

    logger.info(f"NDK toolchain: {toolchain_bin}")
    logger.info(f"NDK target: {ndk_target}{api_level}")

    env.Replace(
        CC = cc,
        CXX = cxx,
        AR = ar,
        RANLIB = ranlib,
    )

    # android_native_app_glue headers live inside the NDK sources
    ndk_app_glue_dir = os.path.join(ndk_root, "sources", "android", "native_app_glue")

    env.Append(
        CPPFLAGS = [
            "-fPIC",
        ],
        CPPDEFINES = [
            "ANDROID",
        ],
        CPPPATH = [
            ndk_app_glue_dir,
        ],
    )
