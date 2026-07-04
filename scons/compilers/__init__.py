from sbt.core import builder

def _append_both(env, flags):
    env.Append(CPPFLAGS = flags, LINKFLAGS = flags)

def apply_common_sanitizers(env):
    """Append sanitizer/coverage flags shared by GCC and Clang (asan excepted)."""
    if builder.build_ubsan:
        _append_both(env, ["-fsanitize=undefined", "-fno-omit-frame-pointer"])
    if builder.build_tsan:
        _append_both(env, ["-fsanitize=thread", "-fno-omit-frame-pointer"])
    if builder.build_lsan:
        _append_both(env, ["-fsanitize=leak"])
    if builder.build_hwasan and builder.build_machine == "arm64":
        _append_both(env, ["-fsanitize=hwaddress", "-fno-omit-frame-pointer"])
    if builder.build_coverage:
        _append_both(env, ["--coverage", "-fprofile-arcs", "-ftest-coverage"])

def apply_static_libasan(env):
    """Statically link the asan runtime when building static + asan."""
    if builder.build_static_libs and builder.build_asan:
        env.Append(LINKFLAGS = ["-static-libasan"])
