"""
SBT Architecture Configuration for cross-compilation.
"""

import shutil

# Canonical build selector tokens — single source of truth for the whole SBT.
# Modes are NOT defined here: they are project-owned (app.modes allowlist +
# mode-<x>-* conf keys), consumed via the "mode-" selector prefix.
PLATFORMS = ("linux", "windows", "web", "android")
COMPILERS = ("gcc", "clang", "mingw", "em", "ndk", "zig")
LIBTYPES = ("static", "shared")
LIBCS = ("gnu", "musl")          # user-selectable libc
ANDROID_LIBC = "bionic"          # forced when platform=android
CROSS_STATES = ("native", "cross")

machine_aliases = {
    "aarch64": "arm64",
    "amd64": "x86_64",
    "i686": "i386",
    "armv7l": "arm32",
    "armv6l": "arm32",
    "arm": "arm32",
}

# fmt: off
#                                                                                   meson cross info
architectures = {
    "x86_64":      {"gcc": {"gnu": "x86_64-linux-gnu-",        "musl": "x86_64-linux-musl-"},       "zig": "x86_64-linux-musl",       "vcpkg": "x64",        "meson": {"cpu_family": "x86_64",     "cpu": "x86_64",     "endian": "little"}},
    "x86":         {"gcc": {"gnu": "i686-linux-gnu-",           "musl": "i686-linux-musl-"},          "zig": "i686-linux-musl",         "vcpkg": "x86",        "meson": {"cpu_family": "x86",        "cpu": "i686",       "endian": "little"}},
    "i386":        {"gcc": {"gnu": "i686-linux-gnu-",           "musl": "i686-linux-musl-"},          "zig": "i386-linux-musl",         "vcpkg": "x86",        "meson": {"cpu_family": "x86",        "cpu": "i386",       "endian": "little"}},
    "arm32":       {"gcc": {"gnu": "arm-linux-gnueabihf-",      "musl": "arm-linux-musleabihf-"},     "gnu_alts": ["arm-none-linux-gnueabihf-", "arm-linux-gnueabihf-"], "zig": "arm-linux-musleabihf",   "zig_flags": "-mcpu=generic+v7a", "vcpkg": "arm",   "meson": {"cpu_family": "arm",        "cpu": "armv7",      "endian": "little"}},
    "arm64":       {"gcc": {"gnu": "aarch64-linux-gnu-",        "musl": "aarch64-linux-musl-"},       "zig": "aarch64-linux-musl",     "vcpkg": "arm64",      "meson": {"cpu_family": "aarch64",    "cpu": "aarch64",   "endian": "little"}},
    "riscv64":     {"gcc": {"gnu": "riscv64-linux-gnu-",        "musl": "riscv64-linux-musl-"},       "zig": "riscv64-linux-musl",     "vcpkg": "riscv64",    "meson": {"cpu_family": "riscv64",    "cpu": "riscv64",   "endian": "little"}},
    "riscv32":     {"gcc": {"gnu": "riscv32-linux-gnu-",        "musl": "riscv32-linux-musl-"},       "zig": "riscv32-linux-musl",     "vcpkg": "riscv32",    "meson": {"cpu_family": "riscv32",    "cpu": "riscv32",   "endian": "little"}},
    "loongarch64": {"gcc": {"gnu": "loongarch64-linux-gnu-",    "musl": "loongarch64-linux-musl-"},   "zig": "loongarch64-linux-musl", "vcpkg": "loongarch64", "meson": {"cpu_family": "loongarch64", "cpu": "loongarch64", "endian": "little"}},
    "mips64el":    {"gcc": {"gnu": "mips64el-linux-gnuabi64-",  "musl": "mips64el-linux-musl-"},     "zig": "mips64el-linux-musl",   "vcpkg": "mips64",     "meson": {"cpu_family": "mips64",    "cpu": "mips64",    "endian": "little"}},
    "s390x":       {"gcc": {"gnu": "s390x-linux-gnu-",          "musl": "s390x-linux-musl-"},         "zig": "s390x-linux-musl",       "vcpkg": "s390x",      "meson": {"cpu_family": "s390x",      "cpu": "s390x",     "endian": "big"}},
    "ppc64le":     {"gcc": {"gnu": "powerpc64le-linux-gnu-",    "musl": "powerpc64le-linux-musl-"},   "zig": "powerpc64le-linux-musl", "vcpkg": "ppc64le",    "meson": {"cpu_family": "ppc64",      "cpu": "ppc64le",   "endian": "little"}},
}
# fmt: on

# Machine names usable as bare conf-key selectors (e.g. "x86_64-libs"). Contain
# "_" not "-", so they survive split("-") as single tokens.
MACHINES = tuple(architectures.keys())

# Machine name used in GNU triplets (differs from internal machine name)
_gnu_machine_map = {
    "arm32": "arm",
    "arm64": "aarch64",
}

# qemu-user binary suffix per SBT machine name (qemu-<arch>); defaults to the machine name
_qemu_arch_map = {
    "x86": "i386",
    "arm32": "arm",
    "arm64": "aarch64",
}

# Android NDK target triplets and ABI names per architecture
_ndk_config = {
    "arm64":   {"target": "aarch64-linux-android",    "abi": "arm64-v8a"},
    "arm32":   {"target": "armv7a-linux-androideabi",  "abi": "armeabi-v7a"},
    "x86_64":  {"target": "x86_64-linux-android",     "abi": "x86_64"},
    "x86":     {"target": "i686-linux-android",        "abi": "x86"},
}

# Libraries that don't exist or are built-in with musl libc
musl_excluded_libs = ["pthread", "m", "dl", "rt", "crypt", "util", "xnet", "resolv"]


def register_machines(extra: dict) -> None:
    if extra:
        architectures.update(extra)


def normalize_machine(machine: str) -> str:
    return machine_aliases.get(machine, machine)


def get_config(machine: str) -> dict:
    return architectures.get(normalize_machine(machine), {})


def get_gnu_machine(machine: str) -> str:
    """Get the machine name as used in GNU triplets (e.g. arm32 -> arm, arm64 -> aarch64)"""
    return _gnu_machine_map.get(machine, machine)


def get_qemu_arch(machine: str) -> str:
    """Get the qemu-user binary arch suffix for a machine (e.g. arm64 -> aarch64 => qemu-aarch64)."""
    machine = normalize_machine(machine)
    return _qemu_arch_map.get(machine, machine)


def get_gcc_prefix(machine: str, libc: str) -> str:
    config = get_config(machine)
    if libc == "gnu":
        # Prefer first installed prefix (arm32 needs ARM's "arm-none-linux-gnueabihf" for static libs).
        for prefix in config.get("gnu_alts", []):
            if shutil.which(prefix + "gcc"):
                return prefix
    return config.get("gcc", {}).get(libc, "")


def get_zig_target(machine: str) -> str:
    return get_config(machine).get("zig", "")


def get_zig_flags(machine: str) -> str:
    return get_config(machine).get("zig_flags", "")


def get_vcpkg_machine(machine: str) -> str:
    return get_config(machine).get("vcpkg", machine)


# Pacman/AUR arch names per SBT machine name
_pacman_arch_map = {
    "x86":         "i686",
    "i386":        "i686",
    "arm64":       "aarch64",
    "arm32":       "armv7h",
    "ppc64le":     "powerpc64le",
}


def get_pacman_arch(machine: str) -> str:
    """Return the pacman/AUR arch string for the given SBT machine name."""
    return _pacman_arch_map.get(normalize_machine(machine), machine)


def get_meson_info(machine: str) -> dict:
    """Get meson cross-compilation info (cpu_family, cpu, endian) for the given machine."""
    return get_config(machine).get("meson", {})


def get_ndk_target(machine: str) -> str:
    """Get the Android NDK clang target triplet for the given machine (e.g. aarch64-linux-android)."""
    return _ndk_config.get(normalize_machine(machine), {}).get("target", "")


def get_ndk_abi(machine: str) -> str:
    """Get the Android ABI name for the given machine (e.g. arm64-v8a)."""
    return _ndk_config.get(normalize_machine(machine), {}).get("abi", "")


# ── Cross-compilation system packages ──────────────────────────────────────
# Packages required to cross-compile for each architecture, per package manager.
# "cross" = cross-compiler toolchain, "libc" = target libc headers/libs,
# "platform" = extra platform-specific packages.

cross_packages = {
    # arch: { pkg_manager: [packages] }
    # Note: on apt, g++ cross packages pull libc6-dev-*-cross and linux-libc-dev-*-cross
    # as transitive dependencies. We list them explicitly for robustness and documentation.
    "arm64": {
        "pacman": ["aarch64-linux-gnu-gcc"],
        "apt":    ["gcc-aarch64-linux-gnu", "g++-aarch64-linux-gnu",
                    "linux-libc-dev-arm64-cross"],
        "dnf":    ["gcc-aarch64-linux-gnu", "gcc-c++-aarch64-linux-gnu",
                    "kernel-headers"],
    },
    "arm32": {
        "pacman": ["arm-linux-gnueabihf-gcc"],
        "apt":    ["gcc-arm-linux-gnueabihf", "g++-arm-linux-gnueabihf",
                    "linux-libc-dev-armhf-cross"],
        "dnf":    ["gcc-arm-linux-gnueabihf", "gcc-c++-arm-linux-gnueabihf",
                    "kernel-headers"],
    },
    "riscv64": {
        "pacman": ["riscv64-linux-gnu-gcc"],
        "apt":    ["gcc-riscv64-linux-gnu", "g++-riscv64-linux-gnu",
                    "linux-libc-dev-riscv64-cross"],
        "dnf":    ["gcc-riscv64-linux-gnu", "gcc-c++-riscv64-linux-gnu",
                    "kernel-headers"],
    },
    "riscv32": {
        "pacman": ["riscv32-linux-gnu-gcc"],
        "apt":    ["gcc-riscv32-linux-gnu", "g++-riscv32-linux-gnu"],
    },
    "x86": {
        "pacman": ["lib32-gcc-libs"],
        "apt":    ["gcc-multilib", "g++-multilib"],
        "dnf":    ["gcc-x86_64-linux-gnu", "libstdc++-devel.i686"],
    },
    "loongarch64": {
        "apt": ["gcc-loongarch64-linux-gnu", "g++-loongarch64-linux-gnu"],
    },
    "mips64el": {
        "apt": ["gcc-mips64el-linux-gnuabi64", "g++-mips64el-linux-gnuabi64"],
    },
    "s390x": {
        "pacman": ["s390x-linux-gnu-gcc"],
        "apt":    ["gcc-s390x-linux-gnu", "g++-s390x-linux-gnu",
                    "linux-libc-dev-s390x-cross"],
        "dnf":    ["gcc-s390x-linux-gnu", "gcc-c++-s390x-linux-gnu",
                    "kernel-headers"],
    },
    "ppc64le": {
        "pacman": ["powerpc64le-linux-gnu-gcc"],
        "apt":    ["gcc-powerpc64le-linux-gnu", "g++-powerpc64le-linux-gnu",
                    "linux-libc-dev-ppc64el-cross"],
        "dnf":    ["gcc-ppc64le-linux-gnu", "gcc-c++-ppc64le-linux-gnu",
                    "kernel-headers"],
    },
}

libc_packages = {
    "musl": {
        "pacman": ["musl", "kernel-headers-musl"],
        "apt":    ["musl-tools", "musl-dev"],
        "dnf":    ["musl-gcc", "musl-devel", "kernel-headers"],
    },
}

platform_packages = {
    "windows": {
        "pacman": ["mingw-w64-gcc"],
        "apt":    ["gcc-mingw-w64", "g++-mingw-w64"],
        "dnf":    ["mingw64-gcc", "mingw64-gcc-c++"],
    },
    "web": {
        "pacman": ["emscripten"],
        "apt":    ["emscripten"],
    },
    "android": {
        # Android NDK must be installed separately from developer.android.com
    },
}

# Emulator packages for running cross-built test binaries: qemu-user (foreign linux), wine (windows).
runner_packages = {
    "qemu": {
        "pacman": ["qemu-user-static"],
        "apt":    ["qemu-user-static"],
        "dnf":    ["qemu-user-static"],
    },
    "wine": {
        "pacman": ["wine"],
        "apt":    ["wine"],
        "dnf":    ["wine"],
    },
}


def get_cross_packages(machine: str, pkg_manager: str) -> list:
    """Get cross-compiler packages for a target architecture and package manager."""
    return cross_packages.get(normalize_machine(machine), {}).get(pkg_manager, [])


def get_libc_packages(libc: str, pkg_manager: str) -> list:
    """Get libc packages needed for cross-compilation with a given libc."""
    return libc_packages.get(libc, {}).get(pkg_manager, [])


def get_platform_packages(platform: str, pkg_manager: str) -> list:
    """Get platform-specific packages for cross-compilation."""
    return platform_packages.get(platform, {}).get(pkg_manager, [])


def get_runner_packages(runner: str, pkg_manager: str) -> list:
    """Get packages providing the test emulator (qemu/wine) for a package manager."""
    return runner_packages.get(runner, {}).get(pkg_manager, [])
