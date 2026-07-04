import platform
import glob
import shutil
import subprocess
import os
from os.path import join, dirname, abspath

try:
    from sbt.core import loader
    from sbt.core import architectures
except ImportError:
    from . import loader
    from . import architectures

from site_scons.sbt.build import modules as sbt_modules
from site_scons.sbt.core import utils
from sbt.core import logger

loader.load_env()

###############################################################################
# Utils
###############################################################################

def safe_symlink(src, dst):
    if not os.path.exists(src):
        return False
    if os.path.islink(dst):
        os.remove(dst)
    if not os.path.exists(dst):
        logger.info(f"linking {src} -> {dst}")
        if is_msys():
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy(src, dst)
        else:
            os.symlink(src, dst, target_is_directory=os.path.isdir(src))
    return True

def __get_machine(machine):
    return architectures.normalize_machine(machine)

def get_host_machine():
    return __get_machine(platform.machine().lower())

def get_machine():
    machine = utils.get_opt('machine', None)
    if machine is None:
        # Android defaults to arm64 (most common Android device architecture)
        if __get_platform() == "android":
            machine = "arm64"
        else:
            machine = get_host_machine()
    return __get_machine(machine)

###############################################################################
# OS settings
# from conans/client/tools/oss.py in https://github.com/conan-io
###############################################################################
# from conans/conan/tools/gnu/get_gnu_triplet.py in https://github.com/conan-io
def _build_gnu_triplet(machine, vendor, libc="gnu"):
    machine = architectures.get_gnu_machine(machine)
    op_system = {
        "windows": "w64-mingw32",
        "linux": f"linux-{libc}",
        "darwin": "apple-darwin",
        "android": "linux-android",
        "macos": "apple-darwin",
        "ios": "apple-ios",
        "watchos": "apple-watchos",
        "tvos": "apple-tvos",
        # NOTE: it technically must be "asmjs-unknown-emscripten" or
        # "wasm32-unknown-emscripten", but it's not recognized by old config.sub versions
        "emscripten": "local-emscripten",
        "aix": "ibm-aix",
        "neutrino": "nto-qnx"
    }.get(vendor, vendor)
    if op_system is None:
        raise SystemExit("unknown vendor: {}".format(vendor))
    if vendor in ("linux", "android"):
        if machine in ("armv6", "armv6l", "armv7", "armv7l"):
            # Add 'eabi' for ARM architectures
            op_system += "eabi"
        if machine in ("armv5hf", "armv7hf") and vendor == "linux":
            # Add 'hf' for hard-float ABI
            op_system += "hf"
        if machine == "armv8_32" and vendor == "linux":
            op_system += "_ilp32"
    return "{}-{}".format(machine, op_system)

###############################################################################
# Compiler version detection
###############################################################################

def _detect_compiler_major_version(compiler, machine=None, libc="gnu"):
    """Detect the major version of a compiler, returns empty string on failure."""
    try:
        if compiler in ("gcc", "mingw"):
            if compiler == "mingw":
                cmd = "x86_64-w64-mingw32-gcc"
            elif machine is not None:
                prefix = architectures.get_gcc_prefix(machine, libc)
                cmd = f"{prefix}gcc"
            else:
                cmd = "gcc"
            result = subprocess.run([cmd, "-dumpversion"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return result.stdout.strip().split(".")[0]
        elif compiler == "clang":
            result = subprocess.run(["clang", "--version"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                import re
                match = re.search(r"version\s+(\d+)", result.stdout)
                if match:
                    return match.group(1)
        elif compiler == "em":
            result = subprocess.run(["emcc", "--version"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                import re
                match = re.search(r"(\d+)\.\d+", result.stdout)
                if match:
                    return match.group(1)
        elif compiler == "zig":
            result = subprocess.run(["zig", "version"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                # zig is pre-1.0: breaking changes ride the minor, so keep major.minor
                return ".".join(result.stdout.strip().split(".")[:2])
        elif compiler == "ndk":
            ndk_root = os.getenv("ANDROID_NDK_PATH", "")
            if ndk_root:
                source_props = os.path.join(ndk_root, "source.properties")
                if os.path.isfile(source_props):
                    with open(source_props) as f:
                        for line in f:
                            if line.startswith("Pkg.Revision"):
                                return line.split("=")[1].strip().split(".")[0]
    except Exception:
        pass
    return ""

def get_compiler_version():
    """Get the compiler name with major version suffix, e.g. gcc-15, clang-21"""
    machine = get_machine()
    compiler = get_compiler()
    libc = get_libc()
    version = _detect_compiler_major_version(compiler, machine, libc)
    if version:
        return f"{compiler}-{version}"
    return compiler

def probe_gcc_sysroot(machine=None, libc_=None):
    """Return the cross-compiler sysroot (raw, stripped) or empty string on failure."""
    prefix = architectures.get_gcc_prefix(
        build_machine if machine is None else machine,
        libc if libc_ is None else libc_,
    )
    try:
        result = subprocess.run(
            [prefix + "gcc", "-print-sysroot"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return ""

def probe_libstdcxx_dir(machine=None, libc_=None):
    """Return the abspath dir holding libstdc++.so.6 for the toolchain, or empty string."""
    prefix = architectures.get_gcc_prefix(
        build_machine if machine is None else machine,
        libc if libc_ is None else libc_,
    )
    try:
        result = subprocess.run(
            [prefix + "g++", "-print-file-name=libstdc++.so.6"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            path = result.stdout.strip()
            if path:
                return os.path.abspath(os.path.dirname(path))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return ""

###############################################################################
# Build settings
###############################################################################

def is_termux():
    return "ANDROID_ARGUMENT" in os.environ

def is_msys():
    return "MSYSTEM" in os.environ

def is_msys_mingw():
    return is_msys() and "MINGW" in os.getenv("MSYSTEM")

def __get_platform():
    env = utils.get_opt("platform", "")
    build_platform = (env or platform.system()).lower()
    if "win" in build_platform or is_msys():
        build_platform = "windows"
    return build_platform

def get_compiler():
    build_platform = __get_platform()
    compiler = utils.get_opt("compiler", os.getenv("COMPILER", "gcc"))
    if is_termux():
        compiler = "clang"
    if build_platform == "windows" and not is_msys():
        compiler = "mingw"
    elif build_platform == "web":
        compiler = "em"
    elif build_platform == "android":
        compiler = "ndk"
    return compiler.lower()

def get_platform():
    compiler = get_compiler()
    build_platform = __get_platform()
    if compiler == "mingw":
        build_platform = "windows"
    elif compiler == "em":
        build_platform = "web"
    elif compiler == "ndk":
        build_platform = "android"
    return build_platform

def detect_package_manager():
    """Detect the package manager of the current Linux distribution"""
    # Check for package managers in order of preference/commonality
    pkg_managers = [
        ("apt", ["apt", "apt-get"]),           # Debian, Ubuntu, Mint
        ("pacman", ["pacman"]),                 # Arch, Manjaro
        ("dnf", ["dnf"]),                       # Fedora, RHEL 8+, CentOS 8+
        ("yum", ["yum"]),                       # CentOS, RHEL, Amazon Linux
        ("zypper", ["zypper"]),                 # openSUSE, SLES
        ("apk", ["apk"]),                       # Alpine
        ("emerge", ["emerge"]),                 # Gentoo
        ("xbps", ["xbps-install"]),             # Void Linux
        ("swupd", ["swupd"]),                   # Clear Linux
        ("nix", ["nix-env"]),                   # NixOS
    ]
    
    for pkg_name, binaries in pkg_managers:
        for binary in binaries:
            if shutil.which(binary) is not None:
                return pkg_name
    
    # Fallback: try to detect from system files
    if os.path.exists("/etc/debian_version"):
        return "apt"
    elif os.path.exists("/etc/arch-release"):
        return "pacman"
    elif os.path.exists("/etc/fedora-release"):
        return "dnf"
    elif os.path.exists("/etc/redhat-release"):
        return "yum"
    elif os.path.exists("/etc/SuSE-release") or os.path.exists("/etc/SUSE-brand"):
        return "zypper"
    elif os.path.exists("/etc/alpine-release"):
        return "apk"
    elif os.path.exists("/etc/gentoo-release"):
        return "emerge"
    
    return ""

def get_pkgdep():
    pkgmanager = utils.get_opt("pkgdep", "")
    if pkgmanager == "auto":
        pkgmanager = detect_package_manager()
        if pkgmanager:
            logger.info(f"Auto-detected package manager: {pkgmanager}")
    return pkgmanager.lower()

def get_compile_mode():
    return utils.get_opt("mode", "default").lower()

def has_verbose():
    return (utils.is_opt("verbose") or utils.is_opt("v"))

def has_test():
    return (utils.is_opt("test") or utils.is_opt("t"))

def has_demo():
    return utils.is_opt("demo")

def is_address_sanitizer():
    return utils.is_opt("asan")

def is_ubsan():
    return utils.is_opt("ubsan")

def is_tsan():
    return utils.is_opt("tsan")

def is_lsan():
    return utils.is_opt("lsan")

def is_msan():
    return utils.is_opt("msan")

def is_hwasan():
    return utils.is_opt("hwasan")

def is_coverage():
    return utils.is_opt("coverage")

def has_combined():
    return utils.is_opt("combined")

def do_distribution():
    return utils.get_opt("dist", "") != ""

def get_modules():
    return utils.get_opt("modules", "") or utils.get_opt("m", "")

def get_force_build_modules():
    return utils.get_opt("fmod", "")

def __split_modules(lst):
    return [m for m in lst.split(',') if len(m) > 0]

def get_modules_lst():
    return __split_modules(get_modules())

def get_force_build_modules_lst():
    return __split_modules(get_force_build_modules())

def is_static_libs():
    return utils.is_opt("static")

def force_git_clone():
    return utils.is_opt("fgit")

def get_libc():
    # Android uses bionic libc — force it when platform=android
    if __get_platform() == "android":
        return architectures.ANDROID_LIBC
    libc = utils.get_opt("libc", "gnu").lower()
    if libc not in architectures.LIBCS:
        raise SystemExit("unknown libc: {}".format(libc))
    return libc

def get_cpu():
    """Get the target CPU model/architecture for -march/-mcpu.
    Examples: cortex-a72, x86-64-v3, skylake, rv64gc"""
    return utils.get_opt("cpu", os.getenv("CPU", ""))

def get_cpu_flags(machine: str, cpu: str) -> list:
    """Return the compiler cpu flag(s) for the given machine and cpu value.
    x86/x86_64 use -march=, arm/arm64/other use -mcpu=.
    Returns an empty list if cpu is empty."""
    if not cpu:
        return []
    if machine in ("x86_64", "x86", "i386", "riscv64", "riscv32"):
        return [f"-march={cpu}"]
    else:
        return [f"-mcpu={cpu}"]

def get_host_libc():
    """Detect the host system's libc (gnu or musl)"""
    # Try to check if the system uses musl
    try:
        import subprocess
        # Check if ldd is using musl
        result = subprocess.run(['ldd', '--version'], capture_output=True, text=True)
        if 'musl' in result.stdout.lower() or 'musl' in result.stderr.lower():
            return "musl"
    except:
        pass
    # Default to gnu for most systems
    return "gnu"

###############################################################################
# Build initialisation
###############################################################################

# compilation
libc = get_libc()
build_compiler = get_compiler()
build_compiler_version = get_compiler_version()
build_cpu = get_cpu()
host_libc = get_host_libc()
host_machine = get_host_machine()
build_machine = get_machine()
build_mode = get_compile_mode()
build_static_libs = is_static_libs()
liblink = "static" if build_static_libs else "shared"

build_asan = is_address_sanitizer()
build_ubsan = is_ubsan()
build_tsan = is_tsan()
build_lsan = is_lsan()
build_msan = is_msan()
build_hwasan = is_hwasan()
build_coverage = is_coverage()
build_combined = has_combined()
build_tests = has_test()
build_demo = has_demo()
build_verbose = has_verbose()
logger.set_verbose(build_verbose)

# platform
build_platform = get_platform()
host_platform = "linux"  # sbt runs on linux
build_on_termux = is_termux()
build_for_windows = build_platform == "windows"
build_for_linux = build_platform == "linux"
build_for_android = build_platform == "android"

def get_gnu_triplet():
    return _build_gnu_triplet(build_machine, build_platform, libc)

# core/builder.py -> root/site_scons/sbt
sbt_path = abspath(dirname(dirname(__file__)))

# core/builder.py -> root
build_root_path = abspath(dirname(dirname(dirname(dirname(__file__)))))

# base directory modules are read from. defaults to root (modules at <root>/<modname>).
# overridable via app.py 'modules_path' (relative to root) through set_modules_path().
build_modules_path = build_root_path

def set_modules_path(modules_path):
    global build_modules_path
    build_modules_path = join(build_root_path, modules_path) if modules_path else build_root_path

# build dir path next to root
build_entry_path = join(build_root_path, "build")
# last build link path
build_last_link_path = join(build_entry_path, "last")
# build full path: <machine>-<platform>-<libc>/<compiler>-<version>/<mode>/<static|dynamic>
build_path = join(build_entry_path, f"{build_machine}-{build_platform}-{libc}", build_compiler_version, build_mode, liblink)
# distribution path inside the build variant dir
build_dist_path = join(build_path, "dist")

build_extlib_path = join(build_path, "extlib")
build_extlib_bin_path = join(build_extlib_path, "bin")
build_extlib_lib_path = join(build_extlib_path, "lib")
build_extlib_hdr_path = join(build_extlib_path, "include")
build_extlib_etc_path = join(build_extlib_path, "etc")
build_extlib_res_path = join(build_extlib_path, "res")

build_bin_path = join(build_path, "bin")
build_lib_path = join(build_path, "lib")
build_hdr_path = join(build_path, "include")
build_etc_path = join(build_path, "etc")
build_share_path = join(build_path, "share")
build_test_path = join(build_path, "test")
build_demo_path = join(build_path, "demo")
build_obj_path = join(build_path, "obj")

# SBT external project dependencies
sbt_deps_path = join(build_root_path, ".sbt-deps")

libs_type = liblink

###############################################################################
# Cross-test runner (qemu-user / wine)
###############################################################################

# Targets the host CPU can execute natively (same ISA, possibly narrower).
_host_native_machines = {
    "x86_64": ["x86_64", "x86", "i386"],
    "arm64":  ["arm64", "arm32"],
}

def host_can_run(machine):
    return machine in _host_native_machines.get(host_machine, [host_machine])

def get_test_bin_ext():
    """Filename suffix of a test binary (".exe" windows, ".js" web/node, "" elsewhere)."""
    if build_platform == "windows":
        return ".exe"
    if build_platform == "web":
        return ".js"
    return ""

def get_test_runner():
    """Emulator command that wraps a cross-built test binary, or "" when it runs natively."""
    if build_platform == "windows":
        return "wine"
    if build_platform == "web":
        return "node"
    if build_platform == "linux" and not host_can_run(build_machine):
        return "qemu-" + architectures.get_qemu_arch(build_machine)
    return ""

def _mingw_runtime_dll_dirs():
    """Dirs holding the mingw runtime DLLs (libstdc++/libgcc/libwinpthread) a shared build needs."""
    runtime_dlls = [
        "libstdc++-6.dll",
        "libgcc_s_seh-1.dll",
        "libgcc_s_dw2-1.dll",
        "libwinpthread-1.dll"
    ]
    candidates = []
    try:
        out = subprocess.run(
            ["x86_64-w64-mingw32-gcc", "-print-search-dirs"],
            capture_output=True, text=True,
        ).stdout
        for line in out.splitlines():
            if line.startswith("install:"):
                candidates.append(line.split(":", 1)[1].strip())
    except Exception:
        pass
    gcc_path = shutil.which("x86_64-w64-mingw32-gcc")
    if gcc_path:
        toolchain_prefix = dirname(dirname(gcc_path))
        candidates.append(join(toolchain_prefix, "x86_64-w64-mingw32", "bin"))
    dirs = []
    for d in candidates:
        if d and os.path.isdir(d) and d not in dirs \
                and any(os.path.isfile(join(d, dll)) for dll in runtime_dlls):
            dirs.append(d)
    return dirs

def get_test_runner_env():
    """Runtime env (list of KEY=VAL) the emulator needs; emitted as export lines into .env."""
    runner = get_test_runner()
    if not runner:
        return []
    env = []
    if runner == "wine":
        # keep the prefix in the build tree so `make clean` wipes it
        env.append("WINEPREFIX=" + join(build_test_path, ".wine"))
        # silence wine chatter polluting gtest output
        env.append("WINEDEBUG=-all")
        # stop winemenubuilder writing desktop entries outside WINEPREFIX
        env.append("WINEDLLOVERRIDES=winemenubuilder.exe=d")
        # static mingw has no DLLs -> no WINEPATH needed
        if not build_static_libs:
            # shared build also needs the mingw runtime DLLs (libstdc++/libgcc/libwinpthread)
            wine_paths = [build_lib_path, build_extlib_lib_path, build_extlib_bin_path]
            wine_paths.extend(_mingw_runtime_dll_dirs())
            env.append("WINEPATH=" + ";".join(wine_paths))
    else:
        # qemu dynamic-glibc needs the cross sysroot + lib search path; static-musl needs nothing
        if not build_static_libs:
            # ask the compiler for its sysroot; layout varies (arm-none keeps libc under <prefix>/libc)
            sysroot = probe_gcc_sysroot(build_machine, libc)
            env.append("QEMU_LD_PREFIX=" + abspath(sysroot))
            env.append("QEMU_SET_ENV=LD_LIBRARY_PATH=" + ":".join([build_lib_path, build_extlib_lib_path]))
    return env

###############################################################################
# App settings sanitizer
###############################################################################

def is_cross_building():
    return (host_machine != build_machine) or (host_libc != libc) or (host_platform != build_platform)

def _detect_cpp_modules_backend():
    if build_platform != "linux" or is_cross_building():
        return None
    if build_compiler == "gcc" and cpp_modules_compiler_major >= 15:
        return "gcc"
    if build_compiler == "clang" and cpp_modules_compiler_major >= 21:
        return "clang"
    return None

cpp_modules_compiler_major = int((_detect_compiler_major_version(build_compiler, build_machine, libc) or "0").split(".")[0] or 0)
cpp_modules_backend = _detect_cpp_modules_backend()
is_cpp_modules = cpp_modules_backend is not None

allowed_compilers = architectures.COMPILERS

def get_android_sdk_root():
    """Get Android SDK root path."""
    return utils.get_opt("ANDROID_SDK_PATH", "")

def get_java_home():
    """Get JAVA_HOME path."""
    return utils.get_opt("JAVA_HOME", "")

def get_ndk_root():
    """Get Android NDK root path."""
    return utils.get_opt("ANDROID_NDK_PATH", "")

def get_ndk_api_level():
    """Get Android API level (default 24)."""
    return utils.get_opt("ANDROID_API", "24")

def get_ndk_host_tag():
    """Get the NDK prebuilt host tag (override: ANDROID_NDK_HOST_TAG)."""
    override = utils.get_opt("ANDROID_NDK_HOST_TAG", "")
    if override:
        return override
    system = platform.system().lower()
    if system == "darwin":
        return "darwin-x86_64"
    if system == "windows":
        return "windows-x86_64"
    return "linux-x86_64"

def get_ndk_toolchain_bin():
    """Get the NDK prebuilt toolchain bin directory."""
    ndk_root = get_ndk_root()
    if not ndk_root:
        return ""
    return os.path.join(ndk_root, "toolchains", "llvm", "prebuilt", get_ndk_host_tag(), "bin")

def _enabled_sanitizers():
    """Return dict of {name: bool} for all sanitizer-like build flags."""
    return {
        "asan": build_asan,
        "ubsan": build_ubsan,
        "tsan": build_tsan,
        "lsan": build_lsan,
        "msan": build_msan,
        "hwasan": build_hwasan,
        "coverage": build_coverage,
    }

def _check_unsupported_sanitizers(compiler_label):
    """Log error for any active sanitizer/coverage flag — return False if any active."""
    ok = True
    for name, active in _enabled_sanitizers().items():
        if active:
            logger.error("cannot use {} with {}".format(name, compiler_label))
            ok = False
    return ok

def _force_static_no_sanitizers(sanitizer_label, display_label):
    """Reject sanitizers and force static libs for compilers that require them (ndk/mingw/em)."""
    global build_static_libs
    ok = _check_unsupported_sanitizers(sanitizer_label)
    if not build_static_libs:
        logger.warning("not supported {} without static libs - switching to static libs".format(display_label))
        build_static_libs = True
    return ok

def verify_args(app):
    global build_static_libs
    global libc
    ret = True
    if is_msys() and not is_msys_mingw():
        logger.error("msys2 supported for mingw64 only")
        ret = False
    if build_compiler not in allowed_compilers:
        logger.error("compiler {} is not supported".format(build_compiler))
        ret = False
    app_modes = getattr(app, "modes", None)
    if app_modes is not None and build_mode not in app_modes:
        logger.error("mode {} unknown".format(build_mode))
        ret = False

    # Primary sanitizers are mutually exclusive (different allocators / shadow memory).
    # ubsan and coverage compose freely with any primary.
    primary = {
        "asan": build_asan,
        "tsan": build_tsan,
        "msan": build_msan,
        "hwasan": build_hwasan,
        "lsan": build_lsan,
    }
    active_primary = sorted(n for n, v in primary.items() if v)
    if len(active_primary) > 1:
        logger.error("sanitizers are mutually exclusive — enable only one of {}".format(active_primary))
        ret = False

    if build_msan and build_compiler != "clang":
        logger.error("memory sanitizer (msan) is only supported with clang")
        ret = False

    if build_hwasan and build_machine != "arm64":
        logger.error("hardware-assisted address sanitizer (hwasan) requires arm64 machine, got {}".format(build_machine))
        ret = False

    if build_compiler == "zig":
        if libc != "musl":
            logger.warning("gnu libc is not supported with zig - switching to musl")
            libc = "musl"

    if build_compiler == "ndk":
        ndk_root = get_ndk_root()
        if not ndk_root or not os.path.isdir(ndk_root):
            logger.error("ANDROID_NDK_PATH is not set or does not exist")
            ret = False
        if not _force_static_no_sanitizers("Android NDK", "Android NDK"):
            ret = False

    if build_compiler == "mingw":
        if not _check_unsupported_sanitizers("mingw"):
            ret = False
    elif build_compiler == "em":
        if not _force_static_no_sanitizers("emscripten", "Emscripten"):
            ret = False
    return ret

###############################################################################
# Windows utils
###############################################################################

def _pe_dll_imports(path):
    """DLL names a PE binary imports (cross-compile: ldd can't read PE, use objdump)."""
    objdump = shutil.which("x86_64-w64-mingw32-objdump") or shutil.which("objdump")
    if not objdump:
        return []
    names = []
    try:
        out = subprocess.run([objdump, "-p", path], capture_output=True, text=True).stdout
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("DLL Name:"):
                names.append(line.split(":", 1)[1].strip())
    except Exception:
        pass
    return names

def copy_dll_to_build(generated_lld_binaries):
    build_need_dll_path_lst = [build_bin_path]
    if build_demo:
        build_need_dll_path_lst.append(build_demo_path)

    do_copy = False
    for path in build_need_dll_path_lst:
        if os.path.isdir(path):
            do_copy = True
            break

    if not do_copy:
        return

    # dirs to resolve imported DLL names against: own libs, extlib DLLs, mingw runtime
    dll_search_path_lst = [
        build_lib_path,
        build_extlib_bin_path,
        build_extlib_lib_path,
    ]
    dll_search_path_lst.extend(_mingw_runtime_dll_dirs())
    if is_msys():
        dll_search_path_lst.append("/mingw64/bin")

    def _resolve_dll(name):
        for d in dll_search_path_lst:
            cand = os.path.join(d, name)
            if os.path.isfile(cand):
                return cand
        return None

    # recursively follow imports so transitive DLLs (and their runtime deps) are copied
    dll_found = {}
    seen = set()
    queue = []
    for module_name, binaries_conf in generated_lld_binaries.items():
        for bin_conf in binaries_conf:
            queue.extend(_pe_dll_imports(bin_conf["path"]))

    while queue:
        name = queue.pop()
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        resolved = _resolve_dll(name)
        if resolved:
            dll_found[key] = resolved
            queue.extend(_pe_dll_imports(resolved))

    dll_found = set(dll_found.values())

    if has_verbose():
        for dll in dll_found:
            logger.debug(f"Found expected DLL: {dll}")

    for build_dll_path in build_need_dll_path_lst:
        if not os.path.isdir(build_dll_path):
            continue
        if has_verbose():
            logger.debug(f"Copying DLLs found into: {build_dll_path}")
        for dll_from in dll_found:
            dll_to = os.path.join(build_dll_path, os.path.basename(dll_from))

            if os.path.exists(dll_to):
                if os.path.samefile(dll_from, dll_to):
                    continue
                else:
                    os.remove(dll_to)
            shutil.copyfile(dll_from, dll_to)

###############################################################################
# After build
###############################################################################

def symlink_build():
    if not is_msys():
        safe_symlink(build_path, build_last_link_path)

def distribute_app(app, modules):
    from site_scons.sbt.build.distribution import distribute_app as _dist
    _dist(app, modules)