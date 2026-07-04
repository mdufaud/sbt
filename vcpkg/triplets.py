"""
Triplet scanning, detection, and dynamic generation for vcpkg.

Handles:
  - Scanning vcpkg installation for available triplets
  - Building SBT-specific triplet names (musl, zig, emscripten)
  - Auto-detecting the correct triplet for the current build
  - Dynamically generating musl/zig triplet .cmake files
"""

import os

from sbt.core import architectures
from sbt.core import builder
from sbt.core import logger


def scan_vcpkg_triplets(vcpkg_bin_path: str) -> set:
    """
    Scan the vcpkg installation directories to discover available triplets.
    Returns a set of triplet names (without .cmake extension).
    """
    triplets = set()
    vcpkg_root = os.path.dirname(vcpkg_bin_path)
    for subdir in ["triplets", os.path.join("triplets", "community")]:
        triplet_dir = os.path.join(vcpkg_root, subdir)
        if os.path.isdir(triplet_dir):
            for f in os.listdir(triplet_dir):
                if f.endswith(".cmake"):
                    triplets.add(f[:-6])
    return triplets


def build_sbt_triplet_names(sbt_triplet_path: str, addon_triplet_path: str = None) -> set:
    """
    Build the set of triplet names that SBT can generate dynamically.
    These don't need static .cmake files — they are generated at build time.
    Includes: musl triplets, zig triplets, and static SBT/addon triplets (emscripten).
    """
    triplets = set()

    # Static triplets from SBT and addon directories
    for triplet_dir in [sbt_triplet_path, addon_triplet_path]:
        if triplet_dir and os.path.isdir(triplet_dir):
            for f in os.listdir(triplet_dir):
                if f.endswith(".cmake"):
                    triplets.add(f[:-6])

    # Dynamic musl triplets: <vcpkg_machine>-linux-musl for each architecture
    for machine, config in architectures.architectures.items():
        vcpkg_machine = config.get("vcpkg", machine)
        gcc_musl_prefix = config.get("gcc", {}).get("musl", "")
        if gcc_musl_prefix:
            triplets.add(f"{vcpkg_machine}-linux-musl")

    # Dynamic zig triplets: zig-<vcpkg_machine>-linux-{static,dynamic}
    for machine, config in architectures.architectures.items():
        vcpkg_machine = config.get("vcpkg", machine)
        zig_target = config.get("zig", "")
        if zig_target:
            triplets.add(f"zig-{vcpkg_machine}-linux-static")
            triplets.add(f"zig-{vcpkg_machine}-linux-dynamic")

    return triplets


def detect_triplet(vcpkg_bin_path: str, sbt_triplet_path: str, addon_triplet_path: str = None) -> str:
    """
    Auto-detect the vcpkg triplet for the current build configuration.
    Scans vcpkg's triplet directories at runtime instead of maintaining
    hardcoded lists. Also includes SBT/addon-generated triplets (musl, zig).
    """
    from site_scons.sbt.core import utils

    vcpkg_triplet = utils.get_opt("triplet", None)

    if vcpkg_triplet is None:
        vcpkg_triplets = scan_vcpkg_triplets(vcpkg_bin_path)
        sbt_triplets = build_sbt_triplet_names(sbt_triplet_path, addon_triplet_path)
        all_triplets = vcpkg_triplets | sbt_triplets

        prefix = ""
        suffix = ""
        vcpkg_machine = architectures.get_vcpkg_machine(builder.build_machine)
        vcpkg_platform = builder.build_platform
        vcpkg_liblink = "static" if builder.build_static_libs else "dynamic"
        vcpkg_mode = builder.build_mode

        if builder.build_platform == "web":
            vcpkg_machine = "wasm32"
            vcpkg_platform = "emscripten-threads"

        if builder.build_platform == "windows":
            vcpkg_platform = "mingw"

        if builder.build_platform == "android":
            vcpkg_platform = "android"

        # Zig is a self-contained toolchain: build deps with zig too, via the
        # zig- triplet (chains zig-toolchain.cmake). Must take precedence over
        # the musl check below, since zig always forces libc=musl.
        if builder.build_compiler == "zig":
            prefix = "zig-"
        elif builder.libc == "musl" and builder.build_platform == "linux":
            suffix = "-musl"

        triplet_tries = [
            f"{prefix}{vcpkg_machine}-{vcpkg_platform}{suffix}-{vcpkg_liblink}-{vcpkg_mode}",
            f"{prefix}{vcpkg_machine}-{vcpkg_platform}{suffix}-{vcpkg_liblink}",
            f"{prefix}{vcpkg_machine}-{vcpkg_platform}{suffix}-{vcpkg_mode}",
            f"{prefix}{vcpkg_machine}-{vcpkg_platform}{suffix}"
        ]

        for triplet_try in triplet_tries:
            if triplet_try in all_triplets:
                vcpkg_triplet = triplet_try
                break

        logger.info(f"VCPKG triplet auto-detected as: {vcpkg_triplet}")

    if vcpkg_triplet is None:
        raise RuntimeError("no VCPKG triplet detected")

    return vcpkg_triplet


###############################################################################
# Triplet type detection
###############################################################################

def is_musl_triplet(triplet: str) -> bool:
    """Check if the triplet is a dynamically-generated musl triplet."""
    return triplet.endswith("-musl") and "-linux-musl" in triplet and not triplet.startswith("zig-")


def is_zig_triplet(triplet: str) -> bool:
    """Check if the triplet is a dynamically-generated zig triplet."""
    return triplet.startswith("zig-") and ("-linux-static" in triplet or "-linux-dynamic" in triplet)


###############################################################################
# Dynamic triplet content generation
###############################################################################

def generate_musl_triplet_content(machine: str) -> str:
    """
    Generate the content of a musl triplet .cmake file for the given machine.
    Includes the toolchain definition inline (compiler, ar, ranlib, sysroot isolation).
    Uses architectures.py as the single source of truth.
    """
    config = architectures.get_config(machine)
    if not config:
        raise RuntimeError(f"no architecture config for machine '{machine}'")

    vcpkg_machine = config.get("vcpkg", machine)
    meson_info = config.get("meson", {})
    cmake_processor = meson_info.get("cpu", vcpkg_machine)
    gcc_prefix = config.get("gcc", {}).get("musl", "")

    # Honor static builds: a self-contained `static=1 libc=musl` binary needs the
    # vcpkg deps as .a archives, not .so.
    lib_linkage = "static" if builder.build_static_libs else "dynamic"

    lines = [
        f"# Auto-generated musl triplet for {machine}",
        f"set(CMAKE_SYSTEM_NAME Linux)",
        f"set(CMAKE_SYSTEM_PROCESSOR {cmake_processor})",
        f"set(VCPKG_TARGET_ARCHITECTURE {vcpkg_machine})",
        f"set(VCPKG_CRT_LINKAGE dynamic)",
        f"set(VCPKG_LIBRARY_LINKAGE {lib_linkage})",
        f"set(VCPKG_CMAKE_SYSTEM_NAME Linux)",
        f'set(CMAKE_C_FLAGS "-fPIC" CACHE STRING "" FORCE)',
        f'set(CMAKE_CXX_FLAGS "-fPIC" CACHE STRING "" FORCE)',
    ]

    # Inline toolchain: set cross-compiler and sysroot isolation
    if gcc_prefix:
        lines += [
            "",
            "# Inline cross-compilation toolchain",
            f"set(CMAKE_C_COMPILER {gcc_prefix}gcc)",
            f"set(CMAKE_CXX_COMPILER {gcc_prefix}g++)",
            f'set(CMAKE_AR {gcc_prefix}ar CACHE FILEPATH "Archiver")',
            f'set(CMAKE_RANLIB {gcc_prefix}ranlib CACHE FILEPATH "Ranlib")',
            "set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)",
            "set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)",
            "set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)",
            "set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)",
        ]

    return "\n".join(lines) + "\n"


def generate_zig_triplet_content(machine: str, linkage: str) -> str:
    """
    Generate the content of a zig triplet .cmake file for the given machine.
    linkage: "static" or "dynamic".
    Uses architectures.py for zig target and flags.
    Chains the shared zig-toolchain.cmake for compiler setup.
    """
    config = architectures.get_config(machine)
    if not config:
        raise RuntimeError(f"no architecture config for machine '{machine}'")

    vcpkg_machine = config.get("vcpkg", machine)
    meson_info = config.get("meson", {})
    cmake_processor = meson_info.get("cpu", vcpkg_machine)
    zig_target = config.get("zig", "")
    zig_flags = config.get("zig_flags", "")

    if not zig_target:
        raise RuntimeError(f"no zig target for machine '{machine}'")

    zig_toolchain_path = os.path.join(builder.sbt_path, "vcpkg", "toolchains", "zig-toolchain.cmake").replace("\\", "/")

    c_flags = f"-target {zig_target}"
    if zig_flags:
        c_flags += f" {zig_flags}"
    c_flags += " -fPIC"

    lines = [
        f"# Auto-generated zig triplet for {machine} ({linkage})",
        f"set(CMAKE_SYSTEM_PROCESSOR {cmake_processor})",
        f"set(VCPKG_TARGET_ARCHITECTURE {vcpkg_machine})",
        f"set(VCPKG_CRT_LINKAGE {linkage})",
        f"set(VCPKG_LIBRARY_LINKAGE {linkage})",
        f"set(VCPKG_CMAKE_SYSTEM_NAME Linux)",
        f'set(VCPKG_TARGET_TRIPLET "{zig_target}")',
        f'set(ARCH_TARGET "{zig_target}")',
        f'set(CMAKE_C_FLAGS "{c_flags}" CACHE STRING "" FORCE)',
        f'set(CMAKE_CXX_FLAGS "{c_flags}" CACHE STRING "" FORCE)',
        f'set(VCPKG_CHAINLOAD_TOOLCHAIN_FILE "{zig_toolchain_path}")',
    ]

    return "\n".join(lines) + "\n"


def generate_dynamic_triplet(overlay_dir: str, triplet: str) -> str:
    """
    If the triplet is a dynamically-generated one (musl or zig),
    write its .cmake content into overlay_dir and return the path.
    Returns None if this triplet is not dynamically generated.
    """
    if is_musl_triplet(triplet):
        # Extract machine from triplet: <vcpkg_machine>-linux-musl
        vcpkg_machine = triplet.split("-linux-musl")[0]
        # Reverse-lookup the machine name from vcpkg machine name
        machine = None
        for m, config in architectures.architectures.items():
            if config.get("vcpkg") == vcpkg_machine:
                machine = m
                break
        if not machine:
            raise RuntimeError(f"cannot find architecture for vcpkg machine '{vcpkg_machine}'")
        content = generate_musl_triplet_content(machine)
        triplet_path = os.path.join(overlay_dir, f"{triplet}.cmake")
        with open(triplet_path, "w") as f:
            f.write(content)
        logger.info(f"generated dynamic musl triplet at: {triplet_path}")
        return triplet_path

    if is_zig_triplet(triplet):
        # Extract machine and linkage from triplet: zig-<vcpkg_machine>-linux-{static,dynamic}
        rest = triplet[4:]  # strip "zig-"
        if rest.endswith("-static"):
            linkage = "static"
            vcpkg_machine = rest.rsplit("-linux-static", 1)[0]
        elif rest.endswith("-dynamic"):
            linkage = "dynamic"
            vcpkg_machine = rest.rsplit("-linux-dynamic", 1)[0]
        else:
            return None
        # Reverse-lookup the machine name
        machine = None
        for m, config in architectures.architectures.items():
            if config.get("vcpkg") == vcpkg_machine:
                machine = m
                break
        if not machine:
            raise RuntimeError(f"cannot find architecture for vcpkg machine '{vcpkg_machine}'")
        content = generate_zig_triplet_content(machine, linkage)
        triplet_path = os.path.join(overlay_dir, f"{triplet}.cmake")
        with open(triplet_path, "w") as f:
            f.write(content)
        logger.info(f"generated dynamic zig triplet at: {triplet_path}")
        return triplet_path

    return None
