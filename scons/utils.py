import time
import os
import sys
import shutil

# Pretty utility for verbose output
from pprint import PrettyPrinter
pp = PrettyPrinter(indent=2)


def as_list(value):
    """Normalize any scalar, tuple, SCons NodeList, or other iterable to a plain list."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    if hasattr(value, '__iter__') and not isinstance(value, (str, bytes, dict)):
        try:
            return list(value)
        except TypeError:
            pass
    return [value]


from site_scons.sbt.core.utils import dedupe_keep_order, get_opt

###############################################################################
# Build helpers
###############################################################################

from sbt.core import builder
from sbt.core import logger
from sbt.core import conf

__env_to_suffix_keys = {
    env: "_" + name.replace("-", "_")
    for name, env in conf.CONF_FLAG_ENV.items()
}

def add_env_app_conf(app, env, *keys):
    key = "_".join(keys)
    if builder.build_verbose:
        logger.debug(f"adding env app conf: {key}")
    for envkey, suffix in __env_to_suffix_keys.items():
        concat = key + suffix
        attr = getattr(app, concat, None)
        if attr is not None:
            #prepends
            # env[envkey][:0] = attr
            #append
            if isinstance(attr, list):
                env[envkey].extend(attr)
            else:
                env[envkey].append(attr)

def load_env_packages_config(env, *configs):
    """ Parse multiple pkg-configs: libraries/includes utilities """
    libtype = "--static" if builder.is_static_libs else "--shared"
    return parse_config_command(env, [
        "pkg-config {} --cflags --libs {}".format(config, libtype)
        for config in configs
    ])

def parse_config_command(env, *configs):
    """ Parse configs from binaries outputs """
    if builder.build_platform == "windows" or builder.build_platform == "web":
        return False
    # Skip host pkg-config/pcap-config when cross-compiling: they return host
    # paths (e.g. -I/usr/include) that poison cross builds. The cross_sysroot=
    # option re-enables them, pointing pkg-config at the target sysroot.
    cross_sysroot = ""
    if builder.is_cross_building():
        cross_sysroot = get_opt("cross_sysroot", "")
        if not cross_sysroot:
            return False
    saved_env = None
    if cross_sysroot:
        saved_env = {k: os.environ.get(k) for k in ("PKG_CONFIG_SYSROOT_DIR", "PKG_CONFIG_PATH")}
        os.environ["PKG_CONFIG_SYSROOT_DIR"] = cross_sysroot
        os.environ["PKG_CONFIG_PATH"] = os.pathsep.join([
            os.path.join(cross_sysroot, "usr", "lib", "pkgconfig"),
            os.path.join(cross_sysroot, "usr", "share", "pkgconfig"),
        ])
    try:
        for config in configs:
            try:
                env.ParseConfig(config)
            except OSError as e:
                logger.warning("config '{}' not found".format(config))
    finally:
        if saved_env is not None:
            for k, v in saved_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

# def __do_copy(src, dst, *, follow_symlinks=True):
#     do_copy = True
#     if os.path.isfile(dst):
#         src_mtime = os.path.getmtime(src)
#         dst_mtime = os.path.getmtime(dst)
#         if dst_mtime > src_mtime:
#             do_copy = False
#     if do_copy:
#         return shutil.copy2(src, dst, follow_symlinks=follow_symlinks)
#     return dst

def install_module_res_into_build(env, module_name, src, dst, must_exist = True):
    """Register build-time Install nodes copying MODNAME/SRC into build/DST.

    Replaces the former eager shutil copy: as SCons nodes these participate in
    the dependency graph (incremental rebuild when a resource changes) and honor
    --dry-run / clean natively. Returns the created nodes.
    """
    src = str(src)
    dst = str(dst)
    module_res = os.path.join(builder.build_modules_path, module_name, src)
    build_output = os.path.join(builder.build_path, dst)
    nodes = []
    if os.path.isfile(module_res):
        nodes = as_list(env.InstallAs(build_output, module_res))
    elif os.path.isdir(module_res):
        for root, _dirs, files in os.walk(module_res):
            rel = os.path.relpath(root, module_res)
            target_dir = build_output if rel == "." else os.path.join(build_output, rel)
            for fname in files:
                nodes += as_list(env.Install(target_dir, os.path.join(root, fname)))
    elif must_exist:
        raise RuntimeError("for module {} resource {} not found".format(module_name, module_res))
    if nodes:
        if builder.has_verbose():
            logger.info("installing resources of module {}/{} -> build/{}".format(module_name, src, dst))
    return nodes


###############################################################################
# Scons helpers
###############################################################################

__node_count = 0
__node_count_max = 0

def get_progress_bar_function(targets):
    global __node_count
    global __node_count_max

    screen = sys.stderr
    if not hasattr(screen, 'isatty') or not screen.isatty():
        return None

    __node_count = 0
    __node_count_max = len(targets)

    def progress_function(node):
        if node not in targets:
            return
        global __node_count
        __node_count += 1
        if __node_count_max > 0:
            screen.write('\r[%3d%%] ' % (__node_count * 100 / __node_count_max))
            screen.flush()

    return progress_function

def build_print_built(binaries, demos, tests):
    for modname, binpaths in binaries.items():
        logger.info("module {} binaries:".format(modname))
        for binpath in binpaths:
            logger.info("\t{}".format(binpath["path"]))

    for modname, demopaths in demos.items():
        logger.info("module {} demos:".format(modname))
        for demopath in demopaths:
            logger.info("\t{}".format(demopath["path"]))

    for modname, testpaths in tests.items():
        logger.info("module {} tests:".format(modname))
        for testpath in testpaths:
            logger.info("\t{}".format(testpath["path"]))

def __print_err(*args):
    print(*args, file=sys.stderr)

def build_print_status(success, failures_message, build_start_time):
    if not success:
        __print_err("==============================================================")
        logger.error("BUILD FAILED (took {:.3f} sec)".format(time.time() - build_start_time))
        logger.error(failures_message)
        __print_err("==============================================================")
    else:
        logger.info("build succeeded (took {:.3f} sec)".format(time.time() - build_start_time))

def build_failure_to_str(bf):
    """ Convert an element of GetBuildFailures() to a string in a useful way """
    import SCons.Errors
    if bf is None: # unknown targets product None in list
        return '(unknown tgt)'
    elif isinstance(bf, SCons.Errors.StopError):
        return str(bf)
    elif bf.node:
        return str(bf.node) + ': ' + bf.errstr
    elif bf.filename:
        return bf.filename + ': ' + bf.errstr
    return 'unknown failure: ' + bf.errstr

def build_status():
    """ Convert the build status to a 2-tuple, (status, msg) """
    from SCons.Script import GetBuildFailures
    build_failures = GetBuildFailures()
    if build_failures:
        # bf is normally a list of build failures; if an element is None,
        # it's because of a target that scons doesn't know anything about.
        success = False
        failures_message = "\n".join(["Failed building %s" % build_failure_to_str(x)
                                        for x in build_failures if x is not None])
    else:
        # if bf is None, the build completed successfully.
        success = True
        failures_message = ''
    return (success, failures_message)


###############################################################################
# Path helpers
###############################################################################

def normalize_module_relative_path(module_name, path):
    """Normalize *path* to be relative to the module root or obj root (if absolute)."""
    path = os.path.normpath(str(path))
    module_root = os.path.join(builder.build_modules_path, module_name)
    module_obj_root = os.path.join(builder.build_obj_path, module_name)
    if os.path.isabs(path):
        if path.startswith(module_root + os.sep):
            return os.path.relpath(path, module_root)
        if path.startswith(module_obj_root + os.sep):
            return os.path.relpath(path, module_obj_root)
        return path
    if path.startswith(module_root + os.sep):
        return os.path.relpath(path, module_root)
    if path.startswith(module_obj_root + os.sep):
        return os.path.relpath(path, module_obj_root)
    return path


def prepend_unique_paths(env, key, values):
    """Prepend *values* to env[*key*], skipping any already present."""
    existing = {str(v) for v in env.get(key, [])}
    to_prepend = []
    for value in values:
        s = str(value)
        if s not in existing and s not in {str(v) for v in to_prepend}:
            to_prepend.append(value)
    if to_prepend:
        env.Prepend(**{key: to_prepend})


###############################################################################
# File replacement helpers
###############################################################################

def fileinput_replace(path, replace_dic):
    """In-place line-by-line string replacement using fileinput."""
    from fileinput import input as file_input
    if not os.path.isfile(path):
        raise RuntimeError("File to replace {} does not exist".format(path))
    for line in file_input(path, inplace=True):
        for key, value in replace_dic.items():
            line = line.replace(key, value)
        print(line, end='')
