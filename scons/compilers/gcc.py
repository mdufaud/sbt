from sbt.core import builder
from sbt.core import architectures
from sbt.scons import compilers

def load_in_env(env):
    prefix = ""
    if builder.is_cross_building():
        prefix = architectures.get_gcc_prefix(builder.build_machine, builder.libc)
        if not prefix:
            raise SystemExit(f"No GCC cross-compiler prefix for machine={builder.build_machine} libc={builder.libc}")

    env.Replace(
        CC = prefix + "gcc",
        CXX = prefix + "g++",
        AR = prefix + "ar",
        RANLIB = prefix + "ranlib",
    )

    # CPU target (-march=/-mcpu= depending on architecture)
    cpu_flags = builder.get_cpu_flags(builder.build_machine, builder.build_cpu)
    if cpu_flags:
        env.Append(CPPFLAGS = cpu_flags)

    # For musl builds, always link libstdc++ and libgcc statically
    # because host system's libstdc++ is built for glibc
    if builder.libc == "musl":
        env.Append(
            LINKFLAGS = ["-static-libgcc", "-static-libstdc++"]
        )

    if builder.build_asan:
        gcc_asan_flags = [
            "-fsanitize=address", # With gcc - has leak enabled by default
            "-fno-omit-frame-pointer", # Leave frame pointers. Allows the fast unwinder to function properly.
            "-fno-common", # helps detect global variables issues
            "-fno-inline" # readable stack traces
        ]
        env.Append(
            CPPFLAGS = gcc_asan_flags,
            LINKFLAGS = gcc_asan_flags
        )
    compilers.apply_common_sanitizers(env)
    if builder.build_static_libs:
        # -no-pie: emit a plain static (non-PIE) binary. A fully static binary gains
        # nothing from being PIE, and static-pie TLS relocations crash under qemu-user.
        env.Append(
            LINKFLAGS = ["-static", "-no-pie", "-static-libgcc", "-static-libstdc++"]
        )
    compilers.apply_static_libasan(env)