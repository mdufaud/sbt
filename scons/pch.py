"""SCons-level precompiled header integration.

A dedicated module compiles a header with env.build_header('src/pch.hpp'). A
module consumes it by listing that module in its own 'depends': the consumer's
compile flags must match the ones the header was built with, and the consume
flag lands in CXXFLAGS only. Nothing propagates to dependents of a consumer.

gcc silently falls back to a full parse when a PCH is not usable and clang
hard-errors on macro/option conflicts, so a mismatch is rejected up front.
"""

import hashlib
import os
import shlex
import shutil
import subprocess
from os import path as os_path

from sbt.core import builder, logger

# wrapper drivers with no precompiled-header story
_UNSUPPORTED_COMPILERS = {"zig", "em"}

# clang compares mtime+size of every included file; SCons judges by content
# (MD5-timestamp), so a touched-but-identical header must pass. Needed both when
# the PCH is created and when it is used.
_CLANG_VALIDATE = "-fpch-validate-input-files-content"

# flags that never invalidate a PCH, plus the options taking a separate argument
_IGNORED_PREFIXES = ("-W", "-I", "-isystem", _CLANG_VALIDATE)
_IGNORED_WITH_ARG = {"-I", "-isystem", "-idirafter", "-iquote", "-include", "-include-pch"}


# removes the contiguous token run: a lone "-include" may belong to a user flag
def _drop_flag(flags, flag):
    n = len(flag)
    for i in range(len(flags) - n + 1):
        if list(flags[i:i + n]) == list(flag):
            return list(flags[:i]) + list(flags[i + n:])
    return list(flags)


def backend(env, ctx):
    """Classify the compiler as ('gcc'|'clang', version banner), or None when
    unsupported (zig, emscripten) or when the probe fails. The probe strips a
    leading ccache token: ccache answers --version itself and would hide the
    real driver identity behind gcc-named wrappers (llvm-mingw)."""
    cxx = env.subst("$CXX")
    if cxx in ctx.state.pch_backends:
        return ctx.state.pch_backends[cxx]
    result = None
    if builder.build_compiler not in _UNSUPPORTED_COMPILERS:
        tokens = shlex.split(cxx)
        if tokens and os.path.basename(tokens[0]) == "ccache":
            tokens = tokens[1:]
        if tokens:
            try:
                probe = subprocess.run(tokens + ["--version"], capture_output=True, text=True, timeout=10)
                if probe.returncode == 0:
                    result = ("clang" if "clang" in probe.stdout else "gcc", probe.stdout.strip())
            except Exception:
                result = None
    ctx.state.pch_backends[cxx] = result
    return result


def compat_tokens(env):
    """Compile-line tokens a consumer must share with the header. Warnings,
    include paths and the consume flag itself never matter and are dropped."""
    # imported on use: cli_helper reaches this module from make inclusion, before
    # setup installs SCons
    from SCons.Util import flatten

    tokens = [env.subst("$CXX")]
    for var in ("CXXFLAGS", "CCFLAGS", "CPPFLAGS"):
        skip_arg = False
        for flag in (str(f) for f in flatten(env.get(var, []))):
            if skip_arg:
                skip_arg = False
            elif flag in _IGNORED_WITH_ARG:
                skip_arg = True
            elif not flag.startswith(_IGNORED_PREFIXES):
                tokens.append(flag)
    tokens += env.subst("$_CPPDEFFLAGS").split()
    return sorted(tokens)


def build_header(env, src, ctx, test=False):
    """Compile *src* into a precompiled header owned by this module and
    register it for the modules listing this one in their 'depends', or for
    their test binaries when *test*. Returns the artifact node, or None when
    the compiler has no PCH support."""
    from SCons.Tool import CScanner

    probe = backend(env, ctx)
    if probe is None:
        if not ctx.state.pch_unsupported_logged:
            logger.info("pch: no precompiled-header backend for compiler '{}', skipping".format(env.subst("$CXX")))
            ctx.state.pch_unsupported_logged = True
        return None
    kind, version = probe
    modname = env["APP_MODULE_NAME"]
    # the compiler identity is part of the path: a compiler update must rebuild
    # the artifact, and the action text alone does not change with it
    instance_dir = hashlib.sha256((env.subst("$CXX") + version).encode()).hexdigest()[:12]
    pch_dir = os_path.join(builder.build_pch_path, modname, instance_dir)
    # anchors sit side by side under their own names: a test anchor includes the main one
    anchor_name = os_path.basename(str(src))
    anchor_copy = env.File(os_path.join(pch_dir, anchor_name))
    copy_node = env.Command(anchor_copy, env.File(src), _copy_action)[0]
    compile_cmd = "$CXX -o $TARGET -c $CXXFLAGS $CCFLAGS $_CCCOMCOM -x c++-header -MD -MF ${TARGET.abspath}.d $SOURCE"
    if kind == "gcc":
        # gcc resolves the artifact as the sibling <header>.gch of whatever
        # -include names, and silently reparses the header if it is invalid
        artifact = env.File(str(anchor_copy) + ".gch")
        flag = ["-include", str(anchor_copy)]
    else:
        artifact = env.File(os_path.join(pch_dir, os_path.splitext(anchor_name)[0] + ".pch"))
        flag = ["-include-pch", str(artifact), _CLANG_VALIDATE]
        compile_cmd += " " + _CLANG_VALIDATE
    node = env.Command(artifact, copy_node, compile_cmd, source_scanner=CScanner)[0]
    _track_includes(env, node)
    registry = ctx.state.pch_test_headers if test else ctx.state.pch_headers
    if test and modname in ctx.state.pch_headers:
        # gcc would read the main .gch while it is still being written
        env.Depends(node, ctx.state.pch_headers[modname]["node"])
    registry[modname] = {"node": node, "flag": flag, "tokens": compat_tokens(env), "module": modname}
    logger.info("pch: header module '{}' ({}) compiled{}".format(modname, kind, " for tests" if test else ""))
    return node


def consume(env, dep, ctx):
    """Preload the header of *dep* into *env* when *dep* is a header module:
    reject flag divergence, then append the consume flag to CXXFLAGS only —
    CPPFLAGS would leak it into C compilations, which cannot eat a C++ header."""
    header = ctx.state.pch_headers.get(dep)
    if header is None:
        return
    current = env.get("PCH")
    if current is not None:
        raise RuntimeError("module '{}' depends on several header modules ('{}' and '{}'), only one is supported".format(
            env["APP_MODULE_NAME"], current["module"], dep))
    env["PCH"] = header
    verify(env)
    env.Append(CXXFLAGS=list(header["flag"]))
    _patch_ccache(env["ENV"])


def use_test_header(env, ctx):
    """Swap the header *env* consumes for the test header of the same header
    module, when that module built one."""
    current = env.get("PCH")
    if current is None:
        return
    header = ctx.state.pch_test_headers.get(current["module"])
    if header is None:
        return
    env["CXXFLAGS"] = _drop_flag(env["CXXFLAGS"], current["flag"])
    env["PCH"] = header
    env.Append(CXXFLAGS=header["flag"])


def verify(env):
    """Fail when *env* no longer compiles with the flags its header was built
    with. Re-run on test and demo envs, which gain app-level flags after the
    module env is created."""
    header = env.get("PCH")
    if header is None:
        return
    tokens = compat_tokens(env)
    if tokens == header["tokens"]:
        return
    only_module = sorted(set(tokens) - set(header["tokens"]))
    only_header = sorted(set(header["tokens"]) - set(tokens))
    raise RuntimeError(
        "module '{}' cannot use header module '{}': its C++ compile flags differ "
        "(only in module: {}; only in header module: {}). Align the flags or drop '{}' from the module's depends".format(
            env["APP_MODULE_NAME"], header["module"], only_module, only_header, header["module"]))


def strip(env, log=True):
    """Drop PCH consumption from an env whose sources must not preload the
    header: C++ module units (the -fmodules front-end and the PCH preload are
    not combined on one TU) and sources sbt bundles itself."""
    instance = env.get("PCH")
    if instance is None:
        return
    if log:
        logger.info("pch: C++ module units of '{}' skip header module '{}'".format(
            env.get("APP_MODULE_NAME"), instance["module"]))
    env["CXXFLAGS"] = _drop_flag(env["CXXFLAGS"], instance["flag"])
    del env["PCH"]


def _track_includes(env, node):
    """Depend on every header the previous compile actually read, system ones
    included: the depfile only exists after a first build, which is also the
    only time there is nothing to invalidate."""
    depfile = node.abspath + ".d"
    if not os_path.isfile(depfile):
        return
    with open(depfile) as fd:
        text = fd.read().replace("\\\n", " ")
    deps = shlex.split(text.partition(":")[2])
    # compiler cwd is the top dir; dropped files can vanish (compiler update)
    nodes = [env.File(dep if os_path.isabs(dep) else "#/" + dep) for dep in deps]
    env.Depends(node, [n for n in nodes if os_path.exists(n.abspath)])


def _copy_action(target, source, env):
    dst = str(target[0])
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(str(source[0]), dst)


def _patch_ccache(subprocess_env):
    tokens = set(subprocess_env.get("CCACHE_SLOPPINESS", "").split(","))
    tokens.update(("pch_defines", "time_macros"))
    subprocess_env["CCACHE_SLOPPINESS"] = ",".join(sorted(t for t in tokens if t))
