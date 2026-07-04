from sbt.core import builder

def load_in_env(env):
    prefix = "x86_64-w64-mingw32-"
    env.Replace(
        CC = prefix + "gcc",
        CXX = prefix + "c++",
        AR = prefix + "ar",
        RANLIB = prefix + "ranlib",
    )
    env.Replace(
        SHLIBSUFFIX = ".dll",
        LIBSUFFIX = ".lib",
        LIBPREFIX = "",
    )
    if builder.build_static_libs:
        env.Append(
            LINKFLAGS = ["-static", "-static-libgcc", "-static-libstdc++"]
        )