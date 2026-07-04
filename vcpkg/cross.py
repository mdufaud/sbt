"""
vcpkg cross-compilation helpers: meson/cmake cross toolchains, overlay triplets
(extra flags, host-header isolation, per-port CMake options) and a pkg-config
wrapper that hides host .pc files from cross builds.
"""

import os
import platform
import shutil

from sbt.core import architectures
from sbt.core import builder
from sbt.core import logger
from sbt.vcpkg import triplets


# Force vcpkg to build X11/Wayland from source instead of emitting empty packages
# that expect system libs. Needed on both the cross triplet and the host triplet
# (the host build provides tools like libx11's makekeys).
_X11_WAYLAND_FORCE = [
    "set(X_VCPKG_FORCE_VCPKG_X_LIBRARIES ON)",
    "set(X_VCPKG_FORCE_VCPKG_WAYLAND_LIBRARIES ON)",
]


def _posix(path: str) -> str:
    """Normalize backslashes to '/' for embedding in cmake/sh files."""
    return path.replace("\\", "/")


def _first_existing(paths: list[str]) -> str | None:
    """Return the first path that is an existing file, or None."""
    for path in paths:
        if os.path.isfile(path):
            return path
    return None


def _resolve_compiler_wrapper(
        role: str,
        sbt_toolchains_path: str,
        addon_toolchains_path: str | None,
) -> str | None:
    """
    Find a static compiler wrapper (toolchains/wrappers/) matching the current
    build context, most specific first; addon dir wins over sbt at each level:

      {family}{version}-{libc}-{arch}-{role}.sh   gcc16-musl-x86_64-cc.sh
      {family}{version}-{libc}-{role}.sh          gcc16-musl-cc.sh
      {libc}-{arch}-{role}.sh                     musl-x86_64-cc.sh
      {libc}-{role}.sh                            musl-cc.sh

    family/version come from builder.build_compiler_version ("gcc-16"). Returns
    the absolute path, or None.
    """
    libc = builder.libc or "glibc"
    arch = builder.build_machine

    cv = builder.build_compiler_version
    family, version = cv.split("-", 1) if "-" in cv else (cv, None)

    candidates = []
    if family and version:
        candidates.append(f"{family}{version}-{libc}-{arch}-{role}.sh")
        candidates.append(f"{family}{version}-{libc}-{role}.sh")
    candidates.append(f"{libc}-{arch}-{role}.sh")
    candidates.append(f"{libc}-{role}.sh")

    search_roots = [p for p in (addon_toolchains_path, sbt_toolchains_path) if p]

    for name in candidates:
        for root in search_roots:
            candidate = os.path.join(root, "wrappers", name)
            if os.path.isfile(candidate):
                logger.info(f"using compiler wrapper {name!r} for {role}")
                return candidate
    return None


def generate_cmake_cross_toolchain(
        overlay_dir: str,
        vcpkg_bin_path: str,
        sbt_toolchains_path: str,
        addon_toolchains_path: str | None = None,
) -> str | None:
    """
    Generate a cmake cross toolchain that includes vcpkg's linux.cmake, pins the
    cross-compiler paths, and isolates find_* from host paths. Pinning matters
    for same-arch cross-builds (musl on x86_64): vcpkg only auto-detects the
    cross-compiler when host arch != target, otherwise it falls back to /bin/cc.
    Returns the generated path, or None if linux.cmake is missing.
    """
    vcpkg_root = os.path.dirname(vcpkg_bin_path)
    linux_toolchain = _posix(os.path.join(vcpkg_root, "scripts", "toolchains", "linux.cmake"))
    if not os.path.isfile(linux_toolchain):
        logger.warning(f"cannot find vcpkg linux toolchain at '{linux_toolchain}', skipping cmake cross toolchain")
        return None

    # Cross-compiler sysroot, e.g. /usr/aarch64-linux-gnu
    gcc_prefix = architectures.get_gcc_prefix(builder.build_machine, builder.libc)
    raw_sysroot = builder.probe_gcc_sysroot()
    sysroot = _posix(raw_sysroot) if raw_sysroot else None

    lines = ["# Auto-generated cmake cross-compilation toolchain", ""]

    # Pin cross tools before including linux.cmake so they take precedence.
    if gcc_prefix:
        c_compiler = _resolve_compiler_wrapper("cc", sbt_toolchains_path, addon_toolchains_path) \
            or f"{gcc_prefix}gcc"
        cxx_compiler = _resolve_compiler_wrapper("cxx", sbt_toolchains_path, addon_toolchains_path) \
            or f"{gcc_prefix}g++"
        lines.append(f'set(CMAKE_C_COMPILER "{c_compiler}")')
        lines.append(f'set(CMAKE_CXX_COMPILER "{cxx_compiler}")')
        # Only set tools that exist: Arch's musl package ships gcc/g++/ar/ranlib
        # but not objcopy/strip/nm/ld, where host binutils work fine.
        optional_tools = {
            "CMAKE_AR":      f"{gcc_prefix}ar",
            "CMAKE_RANLIB":  f"{gcc_prefix}ranlib",
            "CMAKE_STRIP":   f"{gcc_prefix}strip",
            "CMAKE_OBJCOPY": f"{gcc_prefix}objcopy",
            "CMAKE_NM":      f"{gcc_prefix}nm",
            "CMAKE_LINKER":  f"{gcc_prefix}ld",
        }
        for cmake_var, tool_cmd in optional_tools.items():
            if shutil.which(tool_cmd):
                lines.append(f'set({cmake_var} "{tool_cmd}" CACHE FILEPATH "{cmake_var}")')
        lines.append("")

    lines += [f'include("{linux_toolchain}")', ""]

    if sysroot:
        lines.append(f'list(APPEND CMAKE_FIND_ROOT_PATH "{sysroot}")')
        # CMAKE_SYSROOT makes cmake's PkgConfig remap host /usr/include results
        # into the sysroot, avoiding host/cross header conflicts.
        lines.append(f'set(CMAKE_SYSROOT "{sysroot}")')

    lines += [
        "",
        "# find_* searches the cross sysroot + vcpkg dirs only, never host paths.",
        "set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)",
        "set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)",
        "set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)",
        "set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)",
        "",
    ]

    toolchain_path = os.path.join(overlay_dir, f"cmake-cross-{builder.build_machine}.cmake")
    with open(toolchain_path, "w") as f:
        f.write("\n".join(lines))

    logger.info(f"generated cmake cross toolchain at: {toolchain_path}")
    return toolchain_path


def build_overlay_triplet_with_flags(app, vcpkg_triplet: str, vcpkg_build_path: str,
                                     vcpkg_bin_path: str, sbt_triplet_path: str,
                                     addon_triplet_path: str = None) -> str | None:
    """
    Build an overlay triplet that includes the base triplet and layers on:
      - extra VCPKG_C/CXX_FLAGS from app.py
      - cross-linux host-header isolation (cmake cross-toolchain + force X11/Wayland)
      - Android NDK toolchain chainload
      - per-port VCPKG_CMAKE_CONFIGURE_OPTIONS (base + platform override)

    Dynamic triplets (musl/zig) have their base generated inline; static ones
    include the resolved .cmake. Returns the overlay dir, or None when nothing
    needs overriding.
    """
    cflags   = getattr(app, "vcpkg_cflags", [])
    cxxflags = getattr(app, "vcpkg_cxxflags", [])
    need_flags = bool(cflags or cxxflags)

    is_cross_linux = builder.is_cross_building() and builder.build_platform == "linux"
    is_android = builder.build_platform == "android"
    is_zig = builder.build_compiler == "zig"  # self-contained: chainloads zig-toolchain.cmake

    # Per-port CMake options: base, then platform/cross override replaces per port.
    cmake_opts = dict(getattr(app, "vcpkg_cmake_configure_options", {}))
    override_attr = (f"vcpkg_cmake_configure_options_cross_{builder.build_platform}"
                     if builder.is_cross_building()
                     else f"vcpkg_cmake_configure_options_{builder.build_platform}")
    for port_name, opts in getattr(app, override_attr, {}).items():
        cmake_opts[port_name] = opts

    # zig+clang's 512-bit AVX-512 needs the 'evex512' feature simdjson's icelake
    # kernel never requests, breaking the baseline musl build; drop it (runtime
    # dispatch falls back to the AVX2/haswell kernel).
    if is_zig:
        cmake_opts.setdefault("simdjson", []).append("-DSIMDJSON_AVX512_ALLOWED=OFF")

    need_cmake_opts = any(cmake_opts.values())
    is_dynamic = triplets.is_musl_triplet(vcpkg_triplet) or triplets.is_zig_triplet(vcpkg_triplet)

    if not (need_flags or is_cross_linux or is_android or need_cmake_opts or is_dynamic):
        return None

    overlay_dir = os.path.join(vcpkg_build_path, "overlay-triplets")
    os.makedirs(overlay_dir, exist_ok=True)

    if is_dynamic:
        dynamic_path = triplets.generate_dynamic_triplet(overlay_dir, vcpkg_triplet)
        if dynamic_path is None:
            logger.warning(f"failed to generate dynamic triplet for '{vcpkg_triplet}'")
            return None
        # Base is ready; bail early when there is nothing more to layer on.
        if not (need_flags or is_cross_linux or need_cmake_opts):
            return overlay_dir
        with open(dynamic_path, "r") as f:
            lines = f.read().rstrip("\n").split("\n")
        lines.append("")
    else:
        vcpkg_root = os.path.dirname(vcpkg_bin_path)
        orig_triplet = _first_existing([
            os.path.join(sbt_triplet_path, f"{vcpkg_triplet}.cmake"),
            *([os.path.join(addon_triplet_path, f"{vcpkg_triplet}.cmake")] if addon_triplet_path else []),
            os.path.join(vcpkg_root, "triplets", f"{vcpkg_triplet}.cmake"),
            os.path.join(vcpkg_root, "triplets", "community", f"{vcpkg_triplet}.cmake"),
        ])
        if orig_triplet is None:
            logger.warning(f"cannot find original triplet file for '{vcpkg_triplet}', skipping overlay generation")
            return None
        lines = ["# Auto-generated overlay triplet", f'include("{orig_triplet}")', ""]

    # vcpkg requires VCPKG_C_FLAGS and VCPKG_CXX_FLAGS to be set together.
    if need_flags:
        lines.append(f'string(APPEND VCPKG_C_FLAGS " {" ".join(cflags)}")')
        lines.append(f'string(APPEND VCPKG_CXX_FLAGS " {" ".join(cxxflags)}")')
        lines.append("")

    if is_cross_linux:
        lines.append("# Force vcpkg to build X11/Wayland from source")
        lines += _X11_WAYLAND_FORCE
        if builder.libc == "musl":
            # musl has no libintl.h (glibc-only); build gettext-libintl from source.
            lines.append("set(X_VCPKG_FORCE_VCPKG_GETTEXT_LIBINTL ON)")
        lines.append("")

        # Expose vcpkg-installed cross headers so meson cc.has_header() checks
        # (e.g. libcap's sys/capability.h) find them. Via flags so both cmake and
        # meson packages pick them up.
        vcpkg_installed_inc = _posix(os.path.join(vcpkg_build_path, "vcpkg_installed", vcpkg_triplet, "include"))
        lines.append(f'string(APPEND VCPKG_C_FLAGS " -I{vcpkg_installed_inc}")')
        lines.append(f'string(APPEND VCPKG_CXX_FLAGS " -I{vcpkg_installed_inc}")')
        lines.append("")

        # No VCPKG_MESON_CROSS_FILE override on purpose: vcpkg auto-generates
        # cross files carrying ADDITIONAL_BINARIES (e.g. wayland_scanner) that
        # meson only finds via the cross file in cross mode. The cmake
        # cross-toolchain below fixes compiler detection instead, and that
        # propagates into vcpkg's generated meson files.
        if not is_zig:
            sbt_toolchains_path = os.path.join(os.path.dirname(sbt_triplet_path), "toolchains")
            addon_toolchains_path = (os.path.join(os.path.dirname(addon_triplet_path), "toolchains")
                                     if addon_triplet_path else None)
            cmake_toolchain_path = generate_cmake_cross_toolchain(
                overlay_dir, vcpkg_bin_path, sbt_toolchains_path, addon_toolchains_path,
            )
            if cmake_toolchain_path:
                lines.append(f'set(VCPKG_CHAINLOAD_TOOLCHAIN_FILE "{_posix(cmake_toolchain_path)}")')
                lines.append("")

    if is_android:
        ndk_root = builder.get_ndk_root()
        api_level = builder.get_ndk_api_level()
        ndk_abi = architectures.get_ndk_abi(builder.build_machine)
        ndk_toolchain = _posix(os.path.join(ndk_root, "build", "cmake", "android.toolchain.cmake"))
        lines += [
            "# Android NDK toolchain",
            f'set(VCPKG_CHAINLOAD_TOOLCHAIN_FILE "{ndk_toolchain}")',
            f'set(ANDROID_ABI "{ndk_abi}")',
            f'set(ANDROID_PLATFORM android-{api_level})',
            "",
        ]

    # Ports whose option list was cleared by a platform override are skipped.
    active_cmake_opts = {k: v for k, v in cmake_opts.items() if v}
    if active_cmake_opts:
        for port_name, opts in active_cmake_opts.items():
            lines.append(f'if(PORT STREQUAL "{port_name}")')
            for opt in opts:
                lines.append(f'  list(APPEND VCPKG_CMAKE_CONFIGURE_OPTIONS "{opt}")')
            lines.append("endif()")
        lines.append("")

    wrapper_path = os.path.join(overlay_dir, f"{vcpkg_triplet}.cmake")
    with open(wrapper_path, "w") as f:
        f.write("\n".join(lines))
    logger.info(f"generated overlay triplet at: {wrapper_path}")

    if is_cross_linux:
        _generate_host_overlay_triplet(overlay_dir, vcpkg_bin_path)

    return overlay_dir


def _generate_host_overlay_triplet(overlay_dir: str, vcpkg_bin_path: str) -> None:
    """Host triplet overlay forcing X11/Wayland so host-side tools build for cross-linux."""
    host_machine = architectures.get_vcpkg_machine(platform.machine())
    host_triplet = f"{host_machine}-linux"
    vcpkg_root = os.path.dirname(vcpkg_bin_path)
    host_orig = _first_existing([
        os.path.join(vcpkg_root, "triplets", f"{host_triplet}.cmake"),
        os.path.join(vcpkg_root, "triplets", "community", f"{host_triplet}.cmake"),
    ])
    if host_orig is None:
        return

    host_lines = [
        "# Auto-generated host overlay triplet for cross-linux X11/Wayland",
        f'include("{host_orig}")',
        "",
        *_X11_WAYLAND_FORCE,
        "",
    ]
    host_wrapper_path = os.path.join(overlay_dir, f"{host_triplet}.cmake")
    with open(host_wrapper_path, "w") as f:
        f.write("\n".join(host_lines))
    logger.info(f"generated host overlay triplet at: {host_wrapper_path}")


def generate_pkgconfig_wrapper(overlay_dir: str, vcpkg_triplet: str,
                               vcpkg_build_path: str, vcpkg_bin_path: str) -> str:
    """
    Write a pkg-config wrapper that hides host .pc files from cross builds.

    vcpkg.cmake adds "/" to CMAKE_PREFIX_PATH under FIND_ROOT_PATH_MODE_*=ONLY,
    so FindPkgConfig appends the host /lib/pkgconfig to PKG_CONFIG_PATH. That is
    searched before PKG_CONFIG_LIBDIR, leaking host .pc files (e.g. egl.pc ->
    -I/usr/include) into the build. The wrapper drops every non-vcpkg
    PKG_CONFIG_PATH entry. Returns the wrapper path.
    """
    vcpkg_installed_base = os.path.join(vcpkg_build_path, "vcpkg_installed", vcpkg_triplet)
    os.makedirs(overlay_dir, exist_ok=True)

    wrapper_path = os.path.join(overlay_dir, "pkg-config-cross-wrapper")
    real_pkgconfig = shutil.which("pkg-config") or "/usr/bin/pkg-config"
    pkgconfig_dirs = ":".join([
        f"{vcpkg_installed_base}/lib/pkgconfig",
        f"{vcpkg_installed_base}/debug/lib/pkgconfig",
        f"{vcpkg_installed_base}/share/pkgconfig",
    ])
    vcpkg_root = os.path.dirname(vcpkg_bin_path)

    script = f"""#!/bin/sh
# Auto-generated pkg-config wrapper for cross-linux builds.
# Keeps only vcpkg paths in PKG_CONFIG_PATH; hides host system .pc files.
export PKG_CONFIG_LIBDIR="{pkgconfig_dirs}"

FILTERED=""
OLDIFS="$IFS"
IFS=":"
for dir in $PKG_CONFIG_PATH; do
  case "$dir" in
    {vcpkg_root}/*|{vcpkg_build_path}/*) FILTERED="${{FILTERED:+$FILTERED:}}$dir" ;;
  esac
done
IFS="$OLDIFS"
export PKG_CONFIG_PATH="$FILTERED"
exec {real_pkgconfig} "$@"
"""
    with open(wrapper_path, "w") as f:
        f.write(script)
    os.chmod(wrapper_path, 0o755)

    logger.info(f"using pkg-config wrapper: {wrapper_path}")
    return wrapper_path
