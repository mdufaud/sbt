import os
import re
import glob
import subprocess

from sbt.core import builder
from sbt.core import architectures
from sbt.scons import compilers

# Common compile flags for every runtime object (libunwind / libc++abi / libc++).
# -std=c++23 is kept out of here (CXXFLAGS only) so the C / assembly unwind
# sources are not handed a C++ standard flag by zig's clang driver.
_RUNTIME_CPPFLAGS = [
    "-O2", "-DNDEBUG", "-nostdinc++",
    "-fvisibility=hidden", "-fvisibility-inlines-hidden", "-fPIC",
    "-Wno-user-defined-literals", "-Wno-covered-switch-default", "-Wno-suggest-override",
]


def _zig_lib_dir(cmd_cxx):
    # `zig env` prints ZON: `.lib_dir = "/usr/lib/zig",`
    zig_bin = cmd_cxx.split()[0]
    try:
        out = subprocess.run([zig_bin, "env"], capture_output=True, text=True, timeout=5).stdout
        m = re.search(r'\.lib_dir\s*=\s*"([^"]+)"', out)
        if m and os.path.isdir(m.group(1)):
            return m.group(1)
    except (OSError, subprocess.SubprocessError):
        pass
    return "/usr/lib/zig"


def _config_defines(cmd_cxx):
    # zig's libc++ config (`_LIBCPP_*`) for the installed version. zig dumps it
    # for its STATIC build, so drop the visibility-annotation kill switch (we
    # WANT the annotations -> exported typeinfo/__cxa_*) and add the removed
    # `unexpected` handlers libcxxabi still references.
    defines = []
    try:
        proc = subprocess.run(
            cmd_cxx.split() + ["-dM", "-E", "-x", "c++", "/dev/null"],
            capture_output=True, text=True, timeout=10,
        )
        for line in proc.stdout.splitlines():
            m = re.match(r"^#define (_LIBCPP_[A-Za-z0-9_]+) (.*)$", line)
            if m and m.group(1) != "_LIBCPP_DISABLE_VISIBILITY_ANNOTATIONS":
                defines.append(f"-D{m.group(1)}={m.group(2)}")
    except (OSError, subprocess.SubprocessError):
        pass
    defines.append("-D_LIBCPP_ENABLE_CXX17_REMOVED_UNEXPECTED_FUNCTIONS")
    return defines


def _objs(obj_builder, srcs, objdir, skip=()):
    # Sources live under zig's install dir, so emit explicit object targets in
    # the build tree (mangled from the absolute path to avoid collisions).
    nodes = []
    for src in srcs:
        if any(s in src for s in skip):
            continue
        mangled = os.path.relpath(src, "/").replace("/", "_")
        nodes += obj_builder(os.path.join(objdir, mangled + ".o"), src)
    return nodes


def _build_zig_runtime(env, cmd_cxx):
    # Build ONE libc++abi.so + libc++.so from zig's own libcxx sources, with
    # libunwind as a static hidden .a linked whole into both (and, via LIBS,
    # into every consumer). This is what lets a multi-.so C++ build share a
    # single typeinfo/RTTI table -> cross-.so catch-by-type + locale work.
    lib = _zig_lib_dir(cmd_cxx)
    cfg = _config_defines(cmd_cxx)
    objdir = os.path.join(builder.build_path, "zig-runtime")

    rt_env = env.Clone()
    rt_env.Replace(
        CCFLAGS=[],
        CXXFLAGS=["-std=c++23"],
        CPPDEFINES=[],
        CPPFLAGS=_RUNTIME_CPPFLAGS + cfg,
        LINKFLAGS=["-fuse-ld=lld", "-nostdlib++"],
        LIBS=[],
    )

    # --- libunwind.a (static, hidden) ---
    unwind_env = rt_env.Clone()
    unwind_env.Append(CPPFLAGS=[
        "-D_LIBUNWIND_IS_NATIVE_ONLY", "-funwind-tables",
        "-fno-exceptions", "-fno-rtti", "-Wa,--noexecstack",
    ])
    unwind_env.Replace(CPPPATH=[
        os.path.join(lib, "libunwind/include"),
        os.path.join(lib, "libunwind/src"),
        os.path.join(lib, "libcxx/include"),
    ])
    unwind_src = [os.path.join(lib, "libunwind/src", f) for f in (
        "libunwind.cpp", "UnwindLevel1.c", "UnwindLevel1-gcc-ext.c",
        "Unwind-sjlj.c", "gcc_personality_v0.c",
        "UnwindRegistersRestore.S", "UnwindRegistersSave.S",
    )]
    unwind_a = unwind_env.StaticLibrary(
        os.path.join(builder.build_lib_path, "unwind"),
        _objs(unwind_env.StaticObject, unwind_src, os.path.join(objdir, "unwind")),
    )

    # --- libc++abi.so ---
    abi_env = rt_env.Clone()
    abi_env.Append(
        CPPFLAGS=[
            "-D_LIBCXXABI_BUILDING_LIBRARY", "-DLIBCXXABI_ENABLE_EXCEPTIONS",
            "-fstrict-aliasing",
        ],
        LINKFLAGS=[
            "-Wl,-soname,libc++abi.so",
            "-Wl,--whole-archive", unwind_a[0].abspath, "-Wl,--no-whole-archive",
            "-lpthread",
        ],
    )
    abi_env.Replace(CPPPATH=[
        os.path.join(lib, "libcxxabi/include"),
        os.path.join(lib, "libcxx/include"),
        os.path.join(lib, "libcxx/src"),
    ])
    abi_src = glob.glob(os.path.join(lib, "libcxxabi/src", "*.cpp"))
    abi_so = abi_env.SharedLibrary(
        os.path.join(builder.build_lib_path, "c++abi"),
        _objs(abi_env.SharedObject, abi_src, os.path.join(objdir, "abi"),
              skip=("cxa_noexception.cpp",)),
    )
    abi_env.Depends(abi_so, unwind_a)

    # --- libc++.so (links libc++abi.so) ---
    cxx_env = rt_env.Clone()
    cxx_env.Append(
        CPPFLAGS=[
            "-DLIBC_NAMESPACE=__llvm_libc_common_utils", "-D_LIBCPP_BUILDING_LIBRARY",
            "-DLIBCXX_BUILDING_LIBCXXABI", "-D_LIBCPP_HAS_NO_PRAGMA_SYSTEM_HEADER",
            "-faligned-allocation",
        ],
        LINKFLAGS=[
            "-Wl,-soname,libc++.so",
            abi_so[0].abspath,
            "-Wl,--whole-archive", unwind_a[0].abspath, "-Wl,--no-whole-archive",
            "-lpthread",
        ],
    )
    cxx_env.Replace(CPPPATH=[
        os.path.join(lib, "libcxx/include"),
        os.path.join(lib, "libcxxabi/include"),
        os.path.join(lib, "libcxx/src"),
        os.path.join(lib, "libcxx/libc"),
    ])
    cxx_src = glob.glob(os.path.join(lib, "libcxx/src", "**", "*.cpp"), recursive=True)
    cxx_so = cxx_env.SharedLibrary(
        os.path.join(builder.build_lib_path, "c++"),
        _objs(cxx_env.SharedObject, cxx_src, os.path.join(objdir, "cxx"),
              skip=("/support/win32/", "/support/ibm/", "/pstl/",
                    "/filesystem/int128_builtins.cpp")),
    )
    cxx_env.Depends(cxx_so, [abi_so, unwind_a])

    return cxx_so, abi_so, unwind_a


def load_in_env(env):
    cmd_cc = "zig cc"
    cmd_cxx = "zig c++"

    target_triple = ""
    extra_flags = ""

    builder.libc = "musl"  # Zig always uses musl

    if builder.is_cross_building():
        target_triple = architectures.get_zig_target(builder.build_machine)
        extra_flags = architectures.get_zig_flags(builder.build_machine)
        if not target_triple:
            raise SystemExit(f"No Zig target for machine={builder.build_machine}")

    if target_triple:
        target_arg = f" -target {target_triple}"
        if extra_flags:
            target_arg += f" {extra_flags}"
        cmd_cc += target_arg
        cmd_cxx += target_arg

    # CPU target (-march=/-mcpu= depending on architecture)
    cpu_flags = builder.get_cpu_flags(builder.build_machine, builder.build_cpu)
    if cpu_flags:
        cpu_str = " ".join(cpu_flags)
        cmd_cc += f" {cpu_str}"
        cmd_cxx += f" {cpu_str}"

    env.Replace(
        CC = cmd_cc,
        CXX = cmd_cxx,
        AR = "zig ar",
        RANLIB = "zig ranlib",
    )

    # SCons' default shared-object suffix ".os" is an unrecognized file
    # extension to zig's clang frontend: it silently drops out of zig's
    # self-hosted toolchain (lld + bundled musl/compiler-rt) into a plain
    # clang-driver pass that picks up the host GCC installation and glibc,
    # producing a glibc-linked .so. Forcing ".o" keeps every object on the
    # self-contained musl path. Shared sources and Object-built test sources
    # live in separate obj subdirs, so there is no target-name collision.
    env.Replace(SHOBJSUFFIX = ".o")

    # Use LLVM's lld linker for better cross-compilation support
    # Disable ubsan to avoid missing runtime symbols
    env.Append(
        CPPFLAGS = ['-fno-sanitize=undefined'],
        LINKFLAGS = ['-fuse-ld=lld', '-fno-sanitize=undefined']
    )

    if builder.build_asan:
        zig_asan_flags = [
            "-fsanitize=address",
            "-fno-omit-frame-pointer",
            "-fno-common",
            "-fno-inline"
        ]
        env.Append(
            CPPFLAGS = zig_asan_flags,
            LINKFLAGS = zig_asan_flags
        )

    if builder.build_static_libs:
        # Static link collapses every module into one binary -> a single
        # bundled libc++ copy, so no shared C++ runtime is needed.
        env.Append(
            LINKFLAGS = ["-static"]
        )
    else:
        # Shared (multi-.so) build: zig ships no shared libc++, so build one
        # here as a prelude and link consumers against it with -nostdlib++.
        # The runtime nodes are linked BY FILE PATH (not -lc++/-lc++abi/-lunwind):
        # zig's driver treats those library names as system libs it provides
        # internally and substitutes its OWN static libc++.a, ignoring -L paths
        # -> every module would bundle a private hidden libc++ copy. Passing the
        # File nodes makes SCons emit the absolute paths (and track the build
        # edge module -> runtime), so consumers share the single libc++.so.
        cxx_so, abi_so, unwind_a = _build_zig_runtime(env, cmd_cxx)
        env.Append(
            CPPFLAGS = _config_defines(cmd_cxx),
            LINKFLAGS = ["-nostdlib++"],
            LIBS = cxx_so + abi_so + unwind_a,
        )

    compilers.apply_static_libasan(env)
