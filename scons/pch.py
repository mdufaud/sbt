"""SCons-level precompiled header integration.

A module owns a PCH via env.build_pch('src/pch.hpp') in its scons.py: the call
records the owner and preloads the PCH into the owner's own environment. Every
module depending on it transitively inherits the same consumption through the
module env factory, exactly like exported libs — consumers declare nothing.

Instances are compiled per environment fingerprint (CXX, CXXFLAGS, CPPFLAGS,
CPPDEFINES): gcc rejects a PCH whose creation saw macros the consumer lacks
(silent fallback to a full parse) and clang hard-errors on macro conflicts,
while both accept differing -I lists and consumer-extra defines. Keying on
that tuple yields the fewest instances that stay valid by construction; -I
differences are excluded on purpose since both compilers are insensitive.

Creation and use always come from clones of the same consuming env, so the
strict flag identity the backends expect holds by construction.
"""

import hashlib
import os
import shlex
import shutil
import subprocess
from os import path as os_path

from SCons.Tool import CScanner

from sbt.core import builder, logger

# wrapper drivers with no precompiled-header story
_UNSUPPORTED_COMPILERS = {"zig", "em"}


def backend(env, ctx):
    """Classify the consuming compiler as 'gcc' or 'clang', or None when
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
                    result = "clang" if "clang" in probe.stdout else "gcc"
            except Exception:
                result = None
    ctx.state.pch_backends[cxx] = result
    return result


def fingerprint(env):
    """Hash the env facts a PCH instance must share with every consumer."""
    from SCons.Util import flatten

    parts = [
        env.subst("$CXX"),
        repr([str(f) for f in env.get("CXXFLAGS", [])]),
        repr([str(f) for f in env.get("CPPFLAGS", [])]),
        repr(sorted(str(d) for d in flatten(env.get("CPPDEFINES", [])))),
    ]
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:12]


def inherit(env, conf, ctx):
    """Attach the registered PCH to a module env transitively depending on its
    owner. Called for every module env right before the module scons.py runs.
    A module opts out with conf key 'pch': False — for dependency trees whose
    headers are feature-macro hostile (python's pyconfig.h redefines what the
    preloaded glibc state already defines, dying under -Werror)."""
    reg = ctx.state.pch
    if reg is None or conf.get("pch") is False or conf["modname"] == reg["owner"]:
        return
    if not _depends_on_owner(ctx.build_modules, conf["modname"], reg["owner"]):
        return
    setup_consumer(env, ctx)


def strip(env):
    """Drop PCH consumption from an env that compiles C++ modules: the
    -fmodules front-end and the PCH preload are not combined on one TU."""
    instance = env.get("PCH")
    if instance is None:
        return
    env["CXXFLAGS"] = [f for f in env["CXXFLAGS"] if f not in instance["flag"]]
    del env["PCH"]


def setup_consumer(env, ctx):
    """Preload the registered PCH into *env*: reuse or compile the matching
    instance and append the consume flag to CXXFLAGS only — CPPFLAGS would
    leak it into C compilations, which cannot eat a C++ header."""
    kind = backend(env, ctx)
    if kind is None:
        if not ctx.state.pch_unsupported_logged:
            logger.info("pch: no precompiled-header backend for compiler '{}', skipping".format(env.subst("$CXX")))
            ctx.state.pch_unsupported_logged = True
        return None
    key = fingerprint(env)
    instance = ctx.state.pch_instances.get(key)
    if instance is None:
        instance = _create_instance(env, ctx, kind, key)
        ctx.state.pch_instances[key] = instance
        logger.info("pch: instance {} ({}) compiled for module '{}'".format(key, kind, env.get("APP_MODULE_NAME")))
    env["PCH"] = instance
    for token in instance["flag"]:
        env.AppendUnique(CXXFLAGS=[token])
    _patch_ccache(env["ENV"])
    return instance


def _depends_on_owner(build_modules, modname, owner):
    seen = set()
    stack = [modname]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        for dep in build_modules.get(name, {}).get("depends", []):
            if dep == owner:
                return True
            stack.append(dep)
    return False


def _create_instance(env, ctx, kind, key):
    anchor = ctx.state.pch["anchor"]
    pch_dir = os_path.join(builder.build_pch_path, key)
    anchor_copy = env.File(os_path.join(pch_dir, "pch.hpp"))
    copy_node = env.Command(anchor_copy, ctx.state.pch["anchor"], _copy_action)[0]
    if kind == "gcc":
        # gcc resolves the artifact as the sibling <header>.gch of whatever
        # -include names, and silently reparses the header if it is invalid
        artifact = env.File(str(anchor_copy) + ".gch")
        flag = ["-include", str(anchor_copy)]
    else:
        artifact = env.File(os_path.join(pch_dir, "pch.pch"))
        flag = ["-include-pch", str(artifact)]
    pch_env = env.Clone()
    # source_scanner tracks the anchor's includes so a dep header change
    # (a vcpkg bump replacing extlib) rebuilds the instance
    node = pch_env.Command(artifact, copy_node,
                           "$CXX -o $TARGET -c $CXXFLAGS $CCFLAGS $_CCCOMCOM -x c++-header $SOURCE",
                           source_scanner=CScanner)[0]
    return {"node": node, "flag": flag}


def _copy_action(target, source, env):
    dst = str(target[0])
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(str(source[0]), dst)


def _patch_ccache(subprocess_env):
    tokens = set(subprocess_env.get("CCACHE_SLOPPINESS", "").split(","))
    tokens.update(("pch_defines", "time_macros"))
    subprocess_env["CCACHE_SLOPPINESS"] = ",".join(sorted(t for t in tokens if t))
