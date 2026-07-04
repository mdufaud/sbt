import os
import shutil
import tarfile
import subprocess
from os.path import join

try:
    from sbt.core import builder as _b
    from sbt.core import logger
except ImportError:
    from site_scons.sbt.core import builder as _b
    from site_scons.sbt.core import logger

from site_scons.sbt.build import modules as sbt_modules
from site_scons.sbt.core import utils
from site_scons.sbt.core import architectures

def _copy_tree_if_exists(src, dst):
    """Recursively copy *src* into *dst* (creating *dst*) when *src* is a directory."""
    if os.path.isdir(src):
        os.makedirs(dst, exist_ok = True)
        shutil.copytree(src, dst, dirs_exist_ok = True)


###############################################################################
# TAR distribution
###############################################################################

def create_tar_package(app):
    os.makedirs(_b.build_dist_path, exist_ok = True)
    tar_path = join(_b.build_dist_path, "{}-{}.tar.gz".format(app.name, app.version))
    logger.info("compressing build to: " + tar_path)
    with tarfile.open(tar_path, "w:gz") as tar:
        # include
        if os.path.isdir(_b.build_hdr_path):
            tar.add(_b.build_hdr_path, arcname = os.path.basename(_b.build_hdr_path))
        # lib
        if os.path.isdir(_b.build_lib_path):
            tar.add(_b.build_lib_path, arcname = os.path.basename(_b.build_lib_path))
        # bin
        if os.path.isdir(_b.build_bin_path):
            tar.add(_b.build_bin_path, arcname = os.path.basename(_b.build_bin_path))
        # etc
        if os.path.isdir(_b.build_etc_path):
            tar.add(_b.build_etc_path, arcname = os.path.basename(_b.build_etc_path))
        # share
        if os.path.isdir(_b.build_share_path):
            tar.add(_b.build_share_path, arcname = os.path.basename(_b.build_share_path))
        # extlibs/include — merged into include/
        if os.path.isdir(_b.build_extlib_hdr_path):
            tar.add(_b.build_extlib_hdr_path, arcname = os.path.basename(_b.build_hdr_path))
        # extlibs/lib — merged into lib/
        if not _b.build_for_windows and os.path.isdir(_b.build_extlib_lib_path):
            tar.add(_b.build_extlib_lib_path, arcname = os.path.basename(_b.build_lib_path))
        # extlibs/bin — merged into bin/
        if os.path.isdir(_b.build_extlib_bin_path):
            tar.add(_b.build_extlib_bin_path, arcname = os.path.basename(_b.build_bin_path))

###############################################################################
# APT distribution
###############################################################################

def _get_deb_multiarch():
    """Return the Debian multiarch triplet, e.g. x86_64-linux-gnu.
    Queries dpkg-architecture when available, falls back to get_gnu_triplet()."""
    try:
        result = subprocess.run(
            ['dpkg-architecture', '-qDEB_HOST_MULTIARCH'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return _b.get_gnu_triplet()

def create_apt_package(app, modules):
    try:
        modules_extlibs = sbt_modules.get_modules_extlibs(app, modules, _b.build_platform)
        dependencies, missing_dep = sbt_modules.get_modules_packages(app, "apt", modules_extlibs)
    except SystemExit as err:
        logger.error(err)
        exit(1)
    maintainers = getattr(app, "maintainers", None)
    if not maintainers:
        logger.error("app.maintainers is required to build a Debian package")
        exit(1)
    apt_path = join(_b.build_dist_path, "apt", "{}-{}".format(app.name, app.version))
    debian_path = join(apt_path, "DEBIAN")
    control_path = join(debian_path, "control")
    logger.info("creating apt package: " + apt_path)
    # debian/control
    os.makedirs(debian_path, exist_ok = True)
    logger.info("creating apt control file: {}".format(control_path))
    with open(control_path, "w") as fd:
        fd.write("Package: {}\n".format(app.name))
        priority = hasattr(app, "priority") and app.priority or "optional"
        fd.write("Priority: {}\n".format(priority))
        fd.write("Maintainer: {}\n".format(maintainers[0]))
        all_contributors = maintainers[1:] + getattr(app, "contributors", [])
        if all_contributors:
            fd.write("Uploaders: {}\n".format(", ".join(all_contributors)))
        if hasattr(app, "url"):
            fd.write("Homepage: {}\n".format(app.url))
        if hasattr(app, "section"):
            fd.write("Section: {}\n".format(app.section))
        fd.write("Architecture: {}\n".format(getattr(app, "architecture", "all")))
        if hasattr(app, "multi_architecture"):
            fd.write("Multi-Arch: {}\n".format(app.multi_architecture))
        fd.write("Version: {}\n".format(app.version))
        if dependencies:
            # Depends: libname (>= version), other_libname (>= other_version)
            fd.write("Depends: {}\n".format(", ".join(["{} (>= {})".format(k, v.split('#')[0]) for k, v in dependencies.items()])))
        fd.write("Description: {}\n".format(app.description))
    # /usr/bin
    _copy_tree_if_exists(_b.build_bin_path, join(apt_path, "usr", "bin"))
    # /usr/include
    _copy_tree_if_exists(_b.build_hdr_path, join(apt_path, "usr", "include"))
    # /usr/share
    _copy_tree_if_exists(_b.build_share_path, join(apt_path, "usr", "share"))
    # /usr/lib/<multiarch-triplet> — prefer dpkg-architecture if available
    _deb_multiarch = _get_deb_multiarch()
    _copy_tree_if_exists(_b.build_lib_path, join(apt_path, "usr", "lib", _deb_multiarch))
    # /etc
    _copy_tree_if_exists(_b.build_etc_path, join(apt_path, "etc"))
    # dpkg-deb to build package — use fakeroot so installed files are owned by root
    if shutil.which("dpkg-deb") is not None:
        if shutil.which("fakeroot") is not None:
            subprocess.call(['fakeroot', 'dpkg-deb', '--build', apt_path])
        else:
            logger.warning("fakeroot not found — package files will have wrong ownership")
            subprocess.call(['dpkg-deb', '--build', apt_path])
    else:
        logger.error("dpkg-deb is missing")

###############################################################################
# PACMAN distribution
###############################################################################

def create_pacman_package(app, modules):
    try:
        modules_extlibs = sbt_modules.get_modules_extlibs(app, modules, _b.build_platform)
        dependencies, missing_dep = sbt_modules.get_modules_packages(app, "pacman", modules_extlibs)
    except SystemExit as err:
        logger.error(err)
        exit(1)
    pacman_path = join(_b.build_dist_path, "pacman", "{}-{}".format(app.name, app.version))
    logger.info("creating pacman package: " + pacman_path)
    os.makedirs(pacman_path, exist_ok = True)
    pkg_build_path = join(pacman_path, "PKGBUILD")
    # change directory to pacman path
    old_cwd = os.getcwd()
    os.chdir(pacman_path)
    logger.info("creating pacman PKGBUILD: {}".format(pkg_build_path))
    # create PKGBUILD file
    with open(pkg_build_path, "w") as fd:
        for maintainer in app.maintainers:
            fd.write('# Maintainer: {}\n'.format(maintainer))
        for uploader in getattr(app, "contributors", []):
            fd.write("# Contributor: {}\n".format(uploader))
        fd.write('\n')
        fd.write('pkgname={}\n'.format(app.name))
        fd.write('pkgver={}\n'.format(app.version))
        fd.write('pkgrel={}\n'.format(1))
        fd.write('pkgdesc="{}"\n'.format(app.description))
        fd.write("arch=('{}')\n".format(architectures.get_pacman_arch(_b.build_machine)))
        if hasattr(app, "url"):
            fd.write('url="{}"\n'.format(app.url))
        if hasattr(app, "license"):
            fd.write("license=('{}')\n".format(app.license))
        if hasattr(app, "section"):
            fd.write("groups=('{}')\n".format(app.section))
        fd.write("makedepends=('git' 'make' 'scons')\n")
        if dependencies:
            # depends=('libname>=version' 'other_libname>=other_version')
            # strip pkgrel suffix (e.g. '1.0.3#15' -> '1.0.3')
            fd.write("depends=({})\n".format(" ".join(["'{}>={}'".format(k, v.split('#')[0]) for k, v in dependencies.items()])))
        if hasattr(app, "pacman_source"):
            fd.write('source=("{}")\n'.format(app.pacman_source))
        fd.write("sha512sums=('SKIP')\n\n")
        fd.write(('build() {{\n'
            '\tcd "${{srcdir}}/${{pkgname}}-${{pkgver}}"\n'
            '\tmake fclean\n'
            '\tmake modules={modules} asan={asan} static={static} '
            'platform={platform} compiler={compiler} machine={machine} libc={libc} mode={mode} ')
        .format(
            modules = utils.get_opt("modules"),
            asan = utils.get_opt("asan", "0"),
            static = utils.get_opt("static", "0"),
            platform = _b.build_platform,
            compiler = _b.build_compiler,
            machine = _b.build_machine,
            libc = _b.libc,
            mode = _b.build_mode,
        ))
        if hasattr(app, "additional_build_env"):
            fd.write(" ".join(["{}={}".format(k, utils.get_opt(k, "0")) for k in app.additional_build_env]))
        else:
            # Auto-deduce additional env vars from module configs:
            # - "conditional-env" keys from conditional_modules (e.g. py=1, lua=1)
            # - "env" dict keys from all modules (e.g. x11=1, wayland=1)
            extra_env_keys = set()
            for mod_conf in getattr(app, "conditional_modules", {}).values():
                cond_env = mod_conf.get("conditional-env")
                if cond_env:
                    extra_env_keys.add(cond_env)
            for mod_conf in getattr(app, "modules", {}).values():
                for env_key in mod_conf.get("env", {}).keys():
                    extra_env_keys.add(env_key)
            if extra_env_keys:
                fd.write(" ".join(["{}={}".format(k, utils.get_opt(k, "0")) for k in sorted(extra_env_keys)]))
        fd.write('\n}\n')
        fd.write('\n')
        fd.write(('package() {{\n'
            '\tcd "${{srcdir}}/${{pkgname}}-${{pkgver}}"\n'
            '\tmake install INSTALL_DESTDIR="${{pkgdir}}" INSTALL_PREFIX="/usr" INSTALL_NOCONFIRM=1 '
            'static={static} platform={platform} compiler={compiler} machine={machine} libc={libc} mode={mode}\n'
        '}}\n').format(
            static = utils.get_opt("static", "0"),
            platform = _b.build_platform,
            compiler = _b.build_compiler,
            machine = _b.build_machine,
            libc = _b.libc,
            mode = _b.build_mode,
        ))
    # generate .SRCINFO if makepkg is available
    srcinfo_path = join(pacman_path, ".SRCINFO")
    if shutil.which("makepkg") is not None:
        result = subprocess.run(["makepkg", "--printsrcinfo"], capture_output=True, text=True)
        if result.returncode == 0:
            with open(srcinfo_path, "w") as fd:
                fd.write(result.stdout)
            logger.info("generated .SRCINFO at: {}".format(srcinfo_path))
        else:
            logger.warning("makepkg --printsrcinfo failed: {}".format(result.stderr.strip()))
    else:
        logger.warning(
            "makepkg not found — generate .SRCINFO manually:\n"
            "  cd {} && makepkg --printsrcinfo > .SRCINFO".format(pacman_path)
        )
    # change back to old directory
    os.chdir(old_cwd)

###############################################################################
# Docker distribution
###############################################################################

# Maps pkg manager name → (install command template, list-join separator)
# {pkgs} is replaced by the space/newline-joined package list
_DOCKER_PKG_INSTALL = {
    "apt":    "apt-get update && apt-get install -y --no-install-recommends \\\n        {pkgs} \\\n    && rm -rf /var/lib/apt/lists/*",
    "apk":    "apk add --no-cache \\\n        {pkgs}",
    "pacman": "pacman -Syu --noconfirm --needed \\\n        {pkgs}",
    "yum":    "yum install -y \\\n        {pkgs}",
    "dnf":    "dnf install -y \\\n        {pkgs}",
}
_DOCKER_PKG_SEPARATOR = {
    "apt":    " \\\n        ",
    "apk":    " \\\n        ",
    "pacman": " \\\n        ",
    "yum":    " \\\n        ",
    "dnf":    " \\\n        ",
}

def _detect_pkg_manager(image):
    """Auto-detect package manager from image name."""
    img = image.lower()
    if any(x in img for x in ("debian", "ubuntu")):
        return "apt"
    if "alpine" in img:
        return "apk"
    if any(x in img for x in ("arch", "manjaro")):
        return "pacman"
    if any(x in img for x in ("fedora", "centos", "rhel", "rocky", "alma", "amazon")):
        return "dnf"
    return "apt"  # safe default


def _get_docker_modules_str(modules):
    """Return a compact string suitable for use as a directory name."""
    return "-".join(sorted(modules.keys()))


def _get_docker_make_args(modules, has_demo):
    """Return a list of make variable assignments for the docker build stage."""
    mods_str = ",".join(sorted(modules.keys()))
    args = [f"m={mods_str}", "mode=release"]
    if has_demo:
        args.append("demo=1")
    if _b.build_static_libs:
        args.append("static=1")
    return args


_DOCKER_DEFAULT_BUILDER_IMAGE = "debian:trixie-slim"
_DOCKER_DEFAULT_RUNTIME_IMAGE = "debian:trixie-slim"


def create_docker_package(app, modules):
    """Generate a multi-stage Dockerfile.

    Builder image: app.docker_builder_image (default: debian:trixie-slim, GCC 14)
    Runtime image: app.docker_runtime_image (default: alpine:latest)
    Builder pkg manager: app.docker_builder_pkg_manager (auto-detected from image name)
    Runtime pkg manager: app.docker_runtime_pkg_manager (auto-detected from image name)
    Override in app.py:
        docker_builder_image = "archlinux:latest"
        docker_builder_pkg_manager = "pacman"
        docker_runtime_image = "ubuntu:26.04"
        docker_runtime_pkg_manager = "apt"

    Output: dist/docker/Dockerfile
    Usage:  docker build -t <app>-<modules> dist/docker/
    """
    has_demo = _b.build_demo
    builder_image = utils.get_opt("docker_builder_image") \
        or getattr(app, "docker_builder_image", _DOCKER_DEFAULT_BUILDER_IMAGE)
    runtime_image = utils.get_opt("docker_runtime_image") \
        or getattr(app, "docker_runtime_image", _DOCKER_DEFAULT_RUNTIME_IMAGE)
    builder_pm = getattr(app, "docker_builder_pkg_manager", _detect_pkg_manager(builder_image))
    runtime_pm = getattr(app, "docker_runtime_pkg_manager", _detect_pkg_manager(runtime_image))

    try:
        modules_extlibs = sbt_modules.get_modules_extlibs(app, modules, _b.build_platform)
        # Include demo_extlibs when demo=1 (build stage only)
        demo_extlibs = {}
        if has_demo and hasattr(app, "demo_extlibs"):
            demo_extlibs = sbt_modules.get_extlibs_versions(app, app.demo_extlibs)
        build_extlibs = dict(modules_extlibs)
        build_extlibs.update(demo_extlibs)
        # Build stage: packages for builder_pm
        build_deps, missing_build = sbt_modules.get_modules_packages(app, builder_pm, build_extlibs)
        # Runtime stage: packages for runtime_pm — demo_extlibs excluded (header-only / build tools)
        runtime_conf_name = "{}_packages".format(runtime_pm)
        if hasattr(app, runtime_conf_name):
            runtime_deps, missing_runtime = sbt_modules.get_modules_packages(app, runtime_pm, modules_extlibs)
        else:
            runtime_deps = {}
            missing_runtime = list(modules_extlibs.keys())
    except SystemExit as err:
        logger.error(err)
        exit(1)

    if missing_build:
        logger.warning("{} build packages not found for: {} — will use make dep".format(
            builder_pm, ", ".join(missing_build)))
    if missing_runtime:
        logger.warning("{} runtime packages not found for: {}".format(
            runtime_pm, ", ".join(missing_runtime)))

    make_args = _get_docker_make_args(modules, has_demo)
    make_args_str = " ".join(make_args)
    # For make dep: skip all extlibs already provided by the builder's pkg manager
    dep_make_args = make_args + ["with-system-packages={}".format(builder_pm)]
    dep_make_args_str = " ".join(dep_make_args)
    modules_str = _get_docker_modules_str(modules)

    docker_path = join(_b.build_dist_path, "docker")
    os.makedirs(docker_path, exist_ok=True)
    dockerfile_path = join(docker_path, "Dockerfile")  # overwritten on each run

    # Toolchain packages always needed in the builder stage
    # Keyed by package manager
    _builder_base_pkgs = {
        "apt":    ["git", "make", "jq", "python3", "scons", "g++", "pkg-config", "ca-certificates"],
        "apk":    ["git", "make", "jq", "python3", "py3-scons", "g++", "pkgconf", "ca-certificates"],
        "pacman": ["git", "make", "jq", "python", "scons", "gcc", "pkgconf", "ca-certificates"],
        "dnf":    ["git", "make", "jq", "python3", "scons", "gcc-c++", "pkgconf", "ca-certificates"],
        "yum":    ["git", "make", "jq", "python3", "scons", "gcc-c++", "pkgconf", "ca-certificates"],
    }
    # vcpkg prerequisites (needed when some extlibs must be fetched)
    _vcpkg_prereqs = {
        "apt":    ["curl", "zip", "unzip", "tar", "cmake", "ninja-build"],
        "apk":    ["curl", "zip", "unzip", "tar", "cmake", "samurai"],
        "pacman": ["curl", "zip", "unzip", "tar", "cmake", "ninja"],
        "dnf":    ["curl", "zip", "unzip", "tar", "cmake", "ninja-build"],
        "yum":    ["curl", "zip", "unzip", "tar", "cmake", "ninja-build"],
    }

    builder_base_pkgs = list(_builder_base_pkgs.get(builder_pm, _builder_base_pkgs["apt"]))
    # If some extlibs are missing from the pkg manager, vcpkg will be used
    if missing_build:
        builder_base_pkgs += _vcpkg_prereqs.get(builder_pm, _vcpkg_prereqs["apt"])
    # Add packages resolved from module extlibs
    all_build_pkgs = builder_base_pkgs + sorted(build_deps.keys())

    sep = _DOCKER_PKG_SEPARATOR.get(builder_pm, " \\\n        ")
    build_pkgs_line = sep.join(all_build_pkgs)
    build_install_cmd = _DOCKER_PKG_INSTALL.get(builder_pm, _DOCKER_PKG_INSTALL["apt"]).format(
        pkgs=build_pkgs_line)

    git_url = getattr(app, "git_url", "")
    build_local = utils.is_opt("docker_build_local")

    sep_rt = _DOCKER_PKG_SEPARATOR.get(runtime_pm, " \\\n        ")
    runtime_pkgs_line = sep_rt.join(sorted(runtime_deps.keys())) if runtime_deps else ""
    runtime_install_cmd = _DOCKER_PKG_INSTALL.get(runtime_pm, _DOCKER_PKG_INSTALL["apk"]).format(
        pkgs=runtime_pkgs_line) if runtime_pkgs_line else ""

    lines = [
        "# Generated by SBT — do not edit manually",
        "# Build: docker build -t {app}-{mods} .".format(app=app.name, mods=modules_str),
        "# Run:   docker run --rm {app}-{mods} <binary>".format(app=app.name, mods=modules_str),
        "",
        "###############################################################################",
        "# Stage 1: builder ({img})".format(img=builder_image),
        "###############################################################################",
        "FROM {img} AS builder".format(img=builder_image),
        "",
        "RUN {cmd}".format(cmd=build_install_cmd),
        "",
    ]

    if build_local:
        lines += [
            "COPY . /src",
            "",
        ]
    else:
        lines += [
            "RUN git clone --depth 1 {url} /src".format(url=git_url),
            "",
        ]

    lines += [
        "WORKDIR /src",
        "",
    ]

    if missing_build:
        lines += [
            "RUN make dep {args}".format(args=dep_make_args_str),
            "",
        ]

    lines += [
        "RUN make {args}".format(args=make_args_str),
        "",
        "RUN make install INSTALL_DESTDIR=/dist INSTALL_PREFIX=/usr INSTALL_NOCONFIRM=1 mode=release"
        # INSTALL_EXTLIBS=1: copies vcpkg-built .so files — not needed when static (all linked in)
        + (" INSTALL_EXTLIBS=1" if missing_build and not _b.build_static_libs else ""),
        "RUN mkdir -p /dist/usr/bin /dist/usr/lib /dist/etc /dist/usr/share",
    ]

    # When builder and runtime images differ, system .so versions may not match.
    # ldd-bundling only works reliably within the same distro family and libc.
    # For cross-distro (e.g. debian→alpine/musl), binaries are not compatible at all.
    # For same-family (e.g. debian→ubuntu), package install in runtime is simpler and safer.
    if builder_image != runtime_image:
        lines += [
            "# Bundle vcpkg-built and project .so that aren't in the runtime pkg manager",
            "# System libs are provided by the runtime image's package manager instead",
        ]

    lines += [
        "",
        "###############################################################################",
        "# Stage 2: runtime ({img})".format(img=runtime_image),
        "###############################################################################",
        "FROM {img}".format(img=runtime_image),
        "",
    ]

    # runtime_install_cmd installs system libs from the runtime's package manager.
    # This works for same-distro and same-family (debian/ubuntu) runtimes.
    # Not needed when static=1: binaries are fully self-contained.
    if runtime_install_cmd and not _b.build_static_libs:
        lines += [
            "RUN {cmd}".format(cmd=runtime_install_cmd),
            "",
        ]

    lines += [
        "COPY --from=builder /dist/usr/bin/  /usr/bin/",
        "COPY --from=builder /dist/usr/lib/  /usr/lib/{app}/".format(app=app.name),
        "COPY --from=builder /dist/etc/      /etc/",
        "",
        "ENV LD_LIBRARY_PATH=/usr/lib/{app}".format(app=app.name),
    ]

    if has_demo:
        lines += [
            "",
            "COPY --from=builder /dist/usr/share/ /usr/share/",
        ]

    content = "\n".join(lines) + "\n"
    with open(dockerfile_path, "w") as fd:
        fd.write(content)
    logger.info("generated Dockerfile at: {}".format(dockerfile_path))

    # .dockerignore — placed next to the Dockerfile (overwritten on each run)
    dockerignore_path = join(docker_path, ".dockerignore")
    with open(dockerignore_path, "w") as fd:
        fd.write("# Generated by SBT\n")
        fd.write("build/\n")
        fd.write("dist/\n")
        fd.write(".vcpkg/\n")
        fd.write(".venv/\n")
        fd.write("*.pyc\n")
        fd.write("__pycache__/\n")
    logger.info("generated .dockerignore at: {}".format(dockerignore_path))


###############################################################################
# Distribution
###############################################################################

def distribute_app(app, modules):
    dist_type = utils.get_opt("dist", None)
    if dist_type is None:
        raise SystemExit("cannot distribute app without its type")
    logger.info("creating {} distribution for app {}".format(dist_type, app.name))
    if dist_type == "tar":
        create_tar_package(app)
    elif dist_type == "apt":
        create_apt_package(app, modules)
    elif dist_type == "pacman":
        create_pacman_package(app, modules)
    elif dist_type == "docker":
        create_docker_package(app, modules)
    else:
        raise SystemExit("cannot distribute app type: {}".format(dist_type))
