from sbt.core import builder

def load_in_env(env):
    # Fil-C is a clang fork shipping its own sysroot (the "pizfix": musl libc,
    # libc++/libc++abi and the libpizlo runtime). The driver locates it relative
    # to its own binary, so no --sysroot/--target is needed — and none is wanted:
    # linux/x86_64 is the only target Fil-C supports.
    env.Replace(
        # compiler for c
        CC = builder.get_filc_bin("clang"),
        # compiler for c++
        CXX = builder.get_filc_bin("clang++"),
        # Fil-C ships no llvm-ar/llvm-ranlib; host binutils read its ELF objects fine
        AR = "ar",
        RANLIB = "ranlib",
    )

    # CPU target (-march=/-mcpu= depending on architecture)
    cpu_flags = builder.get_cpu_flags(builder.build_machine, builder.build_cpu)
    if cpu_flags:
        env.Append(CPPFLAGS = cpu_flags)

    # No sanitizer support: Fil-C's runtime owns the heap and stack layout.
    # builder.verify_args already rejects every sanitizer flag for this compiler.
