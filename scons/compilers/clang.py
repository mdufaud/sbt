from sbt.core import builder
from sbt.scons import compilers

def load_in_env(env):
    if builder.is_cross_building():
        gnu_triplet = builder.get_gnu_triplet()
        env.Append(
            CPPFLAGS = [f"--target={gnu_triplet}"],
            LINKFLAGS = [f"--target={gnu_triplet}"],
        )

    env.Replace(
        # compiler for c
        CC = "clang",
        # compiler for c++
        CXX = "clang++",
        # static library archiver
        AR = "ar",
        # static library indexer
        RANLIB = "ranlib",
    )

    # CPU target (-march=/-mcpu= depending on architecture)
    cpu_flags = builder.get_cpu_flags(builder.build_machine, builder.build_cpu)
    if cpu_flags:
        env.Append(CPPFLAGS = cpu_flags)
    if builder.build_asan:
        clang_asan_flags = [
            "-fsanitize=address,leak",
            "-fno-omit-frame-pointer", # Leave frame pointers. Allows the fast unwinder to function properly.
            "-fno-common", # helps detect global variables issues
            "-fno-inline" # readable stack traces
        ]
        env.Append(
            CPPFLAGS = clang_asan_flags,
            LINKFLAGS = clang_asan_flags
        )
    if builder.build_msan:
        msan_flags = ["-fsanitize=memory", "-fno-omit-frame-pointer", "-fsanitize-memory-track-origins"]
        env.Append(CPPFLAGS = msan_flags, LINKFLAGS = msan_flags)
    compilers.apply_common_sanitizers(env)
    compilers.apply_static_libasan(env)
