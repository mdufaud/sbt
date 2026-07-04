"""
SBT external project dependency resolver.

Clones external SBT projects declared in app.py's `sbt_dependencies`,
builds them as subprocesses with the consumer's platform/compiler config,
and copies their artifacts (libs/headers/bins) into the consumer's extlib/.

Usage (from Makefile):
    python3 site_scons/sbt/build/sbt_deps.py fetch modules=... mode=... platform=... ...

Syntax in app.py:
    sbt_dependencies = {
        "myproject": {
            "git": "https://github.com/example/myproject.git",
            "ref": "main",
            "args": {
                "mode": "release",
                "m": "util,core",
            },
            # "vcpkg": "own",  # use dep's own .vcpkg instead of consumer's
        }
    }
"""

import sys
import os
import shutil
import subprocess

_site_scons = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
if _site_scons not in sys.path:
    sys.path.insert(0, _site_scons)

from sbt.core import loader
from sbt.core import builder
from sbt.core import logger
from site_scons.sbt.core import utils

# ABI-critical args inherited from the consumer — cannot be overridden by dep args
_ABI_ARGS = frozenset({"platform", "compiler", "machine", "libc"})

# Args forwarded from consumer build config to dep builds
_FORWARDED_ARGS = ("platform", "compiler", "machine", "libc", "cpu", "static", "mode")


def _import_app_from_path(app_path):
    """Import an app.py module from an arbitrary path."""
    import importlib.util
    before = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        abs_path = os.path.abspath(app_path)
        if not os.path.isfile(abs_path):
            raise ImportError(f"File not found: {abs_path}")
        spec = importlib.util.spec_from_file_location("dep_app", abs_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load module spec from: {abs_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = before


def _ref_is_branch(dest, ref):
    """True if ref names a remote branch (origin/<ref>), False for tags/SHAs (immutable)."""
    return subprocess.call(
        ["git", "-C", dest, "show-ref", "--verify", "--quiet", f"refs/remotes/origin/{ref}"]
    ) == 0


def _clone_dep(name, config, deps_dir, force):
    """Clone a dependency git repo into deps_dir/name/."""
    git_url = config.get("git")
    ref = config.get("ref", "main")
    if not git_url:
        raise RuntimeError(f"sbt_dependencies['{name}']: missing 'git' URL")

    dest = os.path.join(deps_dir, name)

    if force and os.path.isdir(dest):
        logger.info(f"force re-cloning dependency: {name}")
        shutil.rmtree(dest)

    if os.path.isdir(dest):
        if _ref_is_branch(dest, ref):
            logger.info(f"updating dependency branch: {name} @ {ref}")
            if subprocess.call(["git", "-C", dest, "fetch", "--depth", "1", "origin", ref]) != 0:
                raise RuntimeError(f"git fetch failed for dependency '{name}' @ {ref}")
            if subprocess.call(["git", "-C", dest, "reset", "--hard", f"origin/{ref}"]) != 0:
                raise RuntimeError(f"git reset failed for dependency '{name}' @ {ref}")
        else:
            logger.info(f"dependency already cloned (pinned ref): {name} -> {dest}")
        return dest

    logger.info(f"cloning dependency: {name} ({git_url} @ {ref})")
    args = ["git", "clone", "--branch", ref, "--depth", "1"]
    if config.get("recursive", False):
        args.append("--recursive")
    args.extend([git_url, dest])

    ret = subprocess.call(args)
    if ret != 0:
        raise RuntimeError(f"git clone failed for dependency '{name}': {' '.join(args)}")

    dep_app_path = os.path.join(dest, "app.py")
    if not os.path.isfile(dep_app_path):
        raise RuntimeError(f"cloned dependency '{name}' has no app.py at: {dep_app_path}")

    return dest


def _resolve_all_deps(deps_dict, deps_dir, force, resolved=None, seen_urls=None):
    """
    Recursively discover all SBT dependencies.
    Returns a topologically sorted list (leaf-first) of (name, config, dep_path) tuples.
    """
    if resolved is None:
        resolved = {}
    if seen_urls is None:
        seen_urls = {}

    for name, config in deps_dict.items():
        if name in resolved:
            # Conflict detection: same name, different URL or ref
            existing = resolved[name]
            if existing["config"].get("git") != config.get("git"):
                raise RuntimeError(
                    f"SBT dependency conflict for '{name}': "
                    f"'{existing['config'].get('git')}' vs '{config.get('git')}'"
                )
            if existing["config"].get("ref") != config.get("ref"):
                logger.warning(
                    f"SBT dependency '{name}' requested with different refs: "
                    f"'{existing['config'].get('ref')}' vs '{config.get('ref')}' — using first"
                )
            continue

        dep_path = _clone_dep(name, config, deps_dir, force)
        resolved[name] = {"config": config, "path": dep_path, "transitive_deps": []}

        # Check for transitive SBT dependencies
        dep_app_path = os.path.join(dep_path, "app.py")
        try:
            dep_app = _import_app_from_path(dep_app_path)
            transitive = getattr(dep_app, "sbt_dependencies", {})
            if transitive:
                logger.info(f"dependency '{name}' has {len(transitive)} transitive SBT dep(s)")
                _resolve_all_deps(transitive, deps_dir, force, resolved, seen_urls)
                resolved[name]["transitive_deps"] = list(transitive.keys())
        except ImportError as e:
            logger.warning(f"could not load app.py from dependency '{name}': {e}")

    # Topological sort: leaf-first
    order = []
    visiting = set()

    def visit(dep_name):
        if dep_name in visiting:
            raise RuntimeError(f"circular SBT dependency detected involving '{dep_name}'")
        if dep_name in [n for n, _, _ in order]:
            return
        visiting.add(dep_name)
        entry = resolved[dep_name]
        for transitive_name in entry["transitive_deps"]:
            if transitive_name in resolved:
                visit(transitive_name)
        visiting.discard(dep_name)
        order.append((dep_name, entry["config"], entry["path"]))

    for dep_name in resolved:
        visit(dep_name)

    return order


def _compute_dep_build_args(dep_config):
    """
    Compute the make arguments for building a dependency.
    ABI args come from the consumer, dep_config['args'] can override non-ABI args.
    """
    # Start with consumer's ABI config
    make_args = {}
    for arg in _FORWARDED_ARGS:
        value = getattr(builder, f"build_{arg}", None)
        if value is None:
            value = getattr(builder, arg, None)
        if value is not None and str(value):
            make_args[arg] = str(value)

    # Static needs special handling (it's a bool in builder)
    if builder.build_static_libs:
        make_args["static"] = "1"

    # A dependency is consumed as a library; never build its tests.
    make_args["test"] = "0"

    # Apply dep-specific overrides (skip ABI args and test)
    dep_args = dep_config.get("args", {})
    for key, value in dep_args.items():
        if key in _ABI_ARGS:
            logger.warning(f"ignoring ABI-critical override '{key}' in sbt_dependencies args")
            continue
        if key == "test":
            logger.warning("ignoring 'test' override in sbt_dependencies args: dependency tests are never built")
            continue
        make_args[key] = str(value)

    return make_args


def _make_args_str(make_args):
    """Convert a dict of make args to a command-line string."""
    return " ".join(f"{k}={v}" for k, v in make_args.items() if v)


def _compute_dep_build_path(dep_path, make_args):
    """
    Compute the build output path of a dependency based on its make args.
    Mirrors builder.py's build_path computation.
    """
    from sbt.core import architectures

    dep_machine = make_args.get("machine", builder.build_machine)
    dep_platform = make_args.get("platform", builder.build_platform)
    dep_libc = make_args.get("libc", builder.libc)
    dep_mode = make_args.get("mode", builder.build_mode)
    dep_compiler_version = builder.build_compiler_version
    dep_liblink = "static" if make_args.get("static") == "1" else "shared"

    dep_build_path = os.path.join(
        dep_path, "build",
        f"{dep_machine}-{dep_platform}-{dep_libc}",
        dep_compiler_version,
        dep_mode,
        dep_liblink
    )
    return dep_build_path


def _build_dep(name, dep_path, dep_config, consumer_vcpkg_path, consumer_extlib_path):
    """Build a single dependency via subprocess make."""
    make_args = _compute_dep_build_args(dep_config)
    args_str = _make_args_str(make_args)

    # Determine vcpkg sharing
    use_own_vcpkg = dep_config.get("vcpkg", "") == "own"

    env = os.environ.copy()
    # Drop the consumer make's command-line variables (carried as MAKEFLAGS/
    # MAKEOVERRIDES) so they don't leak into the dependency build and override its
    # own makefile assignments. The dep build gets only the explicit args below.
    for make_var in ("MAKEFLAGS", "MAKEOVERRIDES", "MFLAGS"):
        env.pop(make_var, None)
    if not use_own_vcpkg and consumer_vcpkg_path:
        # Share consumer's vcpkg installation directory via VCPKG_ROOT
        # This is picked up by both the Makefile (skips vcpkg_deploy clone)
        # and install.py (uses this vcpkg binary for triplet detection)
        env["VCPKG_ROOT"] = consumer_vcpkg_path

    # Copy consumer's extlib into dep's extlib so transitive deps are available
    dep_build_path = _compute_dep_build_path(dep_path, make_args)
    dep_extlib_path = os.path.join(dep_build_path, "extlib")
    if os.path.isdir(consumer_extlib_path):
        _copy_tree(consumer_extlib_path, dep_extlib_path)

    # Phase 1: fetch vcpkg dependencies
    logger.info(f"fetching dependencies for: {name}")
    dep_cmd = f"make dep {args_str}"
    logger.info(f"  cmd: {dep_cmd}")
    ret = subprocess.call(dep_cmd, shell=True, cwd=dep_path, env=env)
    if ret != 0:
        raise RuntimeError(f"'make dep' failed for dependency '{name}' (exit {ret})")

    # Phase 2: build
    logger.info(f"building dependency: {name}")
    build_cmd = f"make build {args_str}"
    logger.info(f"  cmd: {build_cmd}")
    ret = subprocess.call(build_cmd, shell=True, cwd=dep_path, env=env)
    if ret != 0:
        raise RuntimeError(f"'make build' failed for dependency '{name}' (exit {ret})")

    return dep_build_path


def _copy_tree(src, dst):
    """Recursively copy src into dst, creating dst if needed, overwriting files."""
    if not os.path.isdir(src):
        return
    # If dst is a symlink (e.g. extlib pointing into the dep's own vcpkg tree from a
    # vcpkg-only run), dissolve it into a real dir of links first. Writing through the
    # dir-symlink would corrupt the dep's vcpkg_installed and create self-referential
    # symlinks (-> "Too many levels of symbolic links" / ELOOP).
    if os.path.islink(dst):
        vcpkg_target = os.path.realpath(dst)
        os.unlink(dst)
        utils.link_tree(vcpkg_target, dst)
    os.makedirs(dst, exist_ok=True)
    for entry in os.scandir(src):
        s = entry.path
        if not os.path.exists(s):
            continue
        d = os.path.join(dst, entry.name)
        if entry.is_dir(follow_symlinks=False):
            _copy_tree(s, d)
        else:
            # Consumer extlib leaves are symlinks (utils.link_tree); copy them as
            # links, not by dereferencing, to avoid duplicating every vcpkg/dep
            # binary into each dep's extlib (and the back-reference SameFileError).
            if os.path.lexists(d):
                # already the same file (s and d resolve identically): leave it,
                # removing+recreating would risk a self-referential link.
                if os.path.realpath(s) == os.path.realpath(d):
                    continue
                os.remove(d)
            shutil.copy2(s, d, follow_symlinks=False)


def _install_artifacts(name, dep_build_path, consumer_extlib_path):
    """Link built artifacts from dep's build output into consumer's extlib/."""
    if not os.path.isdir(dep_build_path):
        logger.warning(f"dependency '{name}' build path not found: {dep_build_path}")
        return

    # If extlib/ is currently a single symlink (created by a prior vcpkg-only run),
    # dissolve it into a real directory with individual symlinks so we can merge into it.
    if os.path.islink(consumer_extlib_path):
        vcpkg_target = os.path.realpath(consumer_extlib_path)
        os.unlink(consumer_extlib_path)
        utils.link_tree(vcpkg_target, consumer_extlib_path)

    # Link dep's own built libs and headers
    for subdir in ("lib", "include", "bin", "etc", "share"):
        src = os.path.join(dep_build_path, subdir)
        if os.path.isdir(src):
            dst = os.path.join(consumer_extlib_path, subdir)
            logger.info(f"installing {name}/{subdir}/ -> {dst}")
            utils.link_tree(src, dst)

    # Also link dep's extlib (transitive vcpkg deps)
    dep_extlib = os.path.join(dep_build_path, "extlib")
    if os.path.isdir(dep_extlib):
        for subdir in ("lib", "include", "bin", "etc", "share"):
            src = os.path.join(dep_extlib, subdir)
            if os.path.isdir(src):
                dst = os.path.join(consumer_extlib_path, subdir)
                logger.info(f"installing {name}/extlib/{subdir}/ -> {dst}")
                utils.link_tree(src, dst)


def fetch():
    """Main entry point: resolve, build, and install all SBT dependencies."""
    app = loader.load_app()
    sbt_deps = getattr(app, "sbt_dependencies", {})
    if not sbt_deps:
        return

    verbose = builder.build_verbose
    force = builder.force_git_clone()
    deps_dir = os.path.join(builder.build_root_path, ".sbt-deps")
    consumer_vcpkg_path = os.path.join(builder.build_root_path, ".vcpkg")
    consumer_extlib_path = builder.build_extlib_path

    logger.info(f"resolving {len(sbt_deps)} SBT dependenc{'y' if len(sbt_deps) == 1 else 'ies'}")

    os.makedirs(deps_dir, exist_ok=True)

    # Phase 1: clone and resolve all deps recursively
    ordered_deps = _resolve_all_deps(sbt_deps, deps_dir, force)

    if verbose:
        logger.debug(f"SBT dependency build order: {[n for n, _, _ in ordered_deps]}")

    # Phase 2: build and install each dep (leaf-first)
    for dep_name, dep_config, dep_path in ordered_deps:
        logger.info(f"processing SBT dependency: {dep_name}")

        dep_build_path = _build_dep(
            dep_name, dep_path, dep_config,
            consumer_vcpkg_path, consumer_extlib_path
        )

        _install_artifacts(dep_name, dep_build_path, consumer_extlib_path)

        logger.info(f"dependency '{dep_name}' installed successfully")

    logger.info(f"all SBT dependencies resolved and installed")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "fetch"
    if action == "fetch":
        try:
            fetch()
        except RuntimeError as e:
            logger.error(str(e))
            sys.exit(1)
    else:
        logger.error(f"unknown action: {action}")
        sys.exit(1)
