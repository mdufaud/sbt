"""
Android APK build helper for sbt.

Provides functions to stage a Gradle project from templates,
replace placeholders, build a SharedLibrary, and package an APK.
"""

import glob
import os
import shutil
import subprocess

from sbt.core import architectures
from sbt.core import builder
from sbt.core import logger

# Path to default Android templates shipped with sbt
_sbt_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(_sbt_dir, "android")

# Java namespace the bundled template ships with; the per-project default namespace
# reuses everything after the leading segment (e.g. "android.terminal").
TEMPLATE_NAMESPACE = "sbt.android.terminal"
TEMPLATE_NAMESPACE_SUFFIX = TEMPLATE_NAMESPACE.split(".", 1)[1]

def get_gradle_build_type(app, mode, default="debug"):
    """Return the Gradle build type (assemble<BuildType>) for an sbt compile mode.

    A project decides which of its sbt compile modes produce the stripped
    ("release") APK by declaring them in the `android_release_modes` list of its
    app.py, e.g.

        android_release_modes = ["release"]
        # or: android_release_modes = ["release", "superReleaseToto2"]

    Every mode listed maps to the `release` Gradle build type (assembleRelease);
    any unlisted mode falls back to `default` (debug). There is deliberately no
    built-in mapping in sbt: a project must opt in explicitly so the mapping is
    always its own decision.
    """
    release_modes = getattr(app, "android_release_modes", None)
    if not isinstance(release_modes, (list, tuple)):
        release_modes = []
    return "release" if mode in release_modes else default


def get_gradle_cache_dir():
    """Return the base dir for the shared Gradle caches for this build config.

    It is a sibling of `lib/`/`demo/` under the triplet's build_path (e.g.
    `build/<triplet>/<mode>/<liblink>/gradle`), so a single `make clean` removes
    every Gradle cache (see makefile/sbt.mk). All APKs built for a configuration
    share it; Gradle keys the configuration cache per project and the local build
    cache per input, so sharing across demos/bins is safe.
    """
    return os.path.join(builder.build_path, "gradle")


def get_abi():
    """Get the Android ABI string for the current build machine."""
    return architectures.get_ndk_abi(builder.build_machine) or "arm64-v8a"


def _replace_placeholders(filepath, replacements):
    """Replace __SBT_*__ placeholders in a text file."""
    try:
        with open(filepath, 'r') as f:
            content = f.read()
    except UnicodeDecodeError:
        return
    original = content
    for key, value in replacements.items():
        content = content.replace(key, value)
    if content != original:
        with open(filepath, 'w') as f:
            f.write(content)


def _copy_tree(src_dir, dst_dir):
    """Copy a directory tree, creating directories as needed."""
    for root, dirs, files in os.walk(src_dir):
        rel_root = os.path.relpath(root, src_dir)
        dst_root = os.path.join(dst_dir, rel_root)
        os.makedirs(dst_root, exist_ok=True)
        for f in files:
            src_file = os.path.join(root, f)
            dst_file = os.path.join(dst_root, f)
            shutil.copy2(src_file, dst_file)


def _remove_empty_dirs(path):
    """Recursively remove empty directories bottom-up."""
    if not os.path.isdir(path):
        return
    for entry in os.scandir(path):
        if entry.is_dir():
            _remove_empty_dirs(entry.path)
    if not os.listdir(path):
        os.rmdir(path)


def load_override_config(android_dir, project_name=None):
    """Load config.py from an override directory if it exists.

    Returns a dict with:
        namespace (str): Java package namespace
        native_activity (bool): whether to use NativeActivity mode
    """
    default_ns = f"{project_name}.{TEMPLATE_NAMESPACE_SUFFIX}"
    defaults = {
        "namespace": default_ns,
        "native_activity": False,
        "permissions": [],
    }
    config_path = os.path.join(android_dir, "config.py")
    if not os.path.isfile(config_path):
        return defaults
    config = {}
    with open(config_path) as f:
        exec(f.read(), config)
    defaults.update({k: v for k, v in config.items() if k in defaults})
    return defaults


def stage_gradle_project(staging_dir, name, module_android_dir=None, permissions=None, project_name=None,
                         gradle_cache_dir=None, ndk_version=None, sign_config=None):
    """Stage a complete Gradle project from templates + optional overrides.

    Args:
        staging_dir: where to create the Gradle project
        name: demo/bin name (used for placeholders)
        module_android_dir: optional module-relative android/ override directory
        permissions: list of Android permission strings (e.g. ["android.permission.INTERNET"])
        project_name: app name used to derive the default Java namespace
        gradle_cache_dir: optional base dir for the Gradle caches (the `.gradle`
            project cache and the local build cache live under this dir). When
            provided, the cache is kept OUTSIDE the staging dir (which is
            re-created on every build) so it survives incremental builds; the
            project's `make clean` wipes it. When None, no cache relocation is
            configured.
        ndk_version: NDK version string (e.g. "28.0.13004108") pinned via the
            `ndkVersion` Gradle property. Pinning it to the actually-installed
            NDK fixes AGP's "Unable to strip ... packaging them as they are"
            warning, which happens when AGP falls back to a strip tool from a
            non-installed NDK.
        sign_config: optional path to a `keystore.properties` file (relative to
            the project root, or absolute) describing how to sign the release
            APK. When provided it adds a keystore loader + `signingConfigs {
            release { ... } }` block to the staged app/build.gradle and
            references it from the release build type; the secrets (passwords)
            are read from the file at Gradle configure time so they are never
            written into the staged build.gradle nor committed. When None, the
            release APK is left unsigned.
    Returns:
        dict with:
            namespace (str): Java namespace
            native_activity (bool): NativeActivity mode
    """
    # Load override config
    if module_android_dir and os.path.isdir(module_android_dir):
        config = load_override_config(module_android_dir, project_name=project_name)
    else:
        config = {"namespace": f"{project_name}.{TEMPLATE_NAMESPACE_SUFFIX}", "native_activity": False}

    # Clean and create staging dir
    if os.path.isdir(staging_dir):
        shutil.rmtree(staging_dir)
    os.makedirs(staging_dir, exist_ok=True)

    # Step 1: Copy default templates
    _copy_tree(TEMPLATE_DIR, staging_dir)

    # Step 1b: Move default java package dir to match the configured namespace
    default_ns_path = os.path.join(staging_dir, "app", "src", "main", "java", *TEMPLATE_NAMESPACE.split("."))
    target_ns_path = os.path.join(staging_dir, "app", "src", "main", "java",
                                  *config["namespace"].split("."))
    if default_ns_path != target_ns_path and os.path.isdir(default_ns_path):
        os.makedirs(os.path.dirname(target_ns_path), exist_ok=True)
        shutil.move(default_ns_path, target_ns_path)
        # Clean up empty parent dirs left by the move
        _remove_empty_dirs(os.path.join(staging_dir, "app", "src", "main", "java", TEMPLATE_NAMESPACE.split(".")[0]))

    # Step 2: If terminal mode, remove NativeActivity-specific files (none in default)
    # If NativeActivity mode, remove terminal-specific files
    if config["native_activity"]:
        terminal_kt = os.path.join(staging_dir, "app", "src", "main", "java",
                                   *config["namespace"].split("."))
        if os.path.isdir(terminal_kt):
            shutil.rmtree(terminal_kt)
        bridge_cpp = os.path.join(staging_dir, "app", "src", "main", "cpp", "terminal_bridge.cpp")
        if os.path.isfile(bridge_cpp):
            os.remove(bridge_cpp)

    # Step 3: Overlay override files
    if module_android_dir and os.path.isdir(module_android_dir):
        for root, dirs, files in os.walk(module_android_dir):
            rel_root = os.path.relpath(root, module_android_dir)
            dst_root = os.path.join(staging_dir, rel_root)
            os.makedirs(dst_root, exist_ok=True)
            for f in files:
                if f == "config.py":
                    continue
                src_file = os.path.join(root, f)
                dst_file = os.path.join(dst_root, f)
                shutil.copy2(src_file, dst_file)

    # Step 4: Replace placeholders in all text files
    abi = get_abi()
    sanitized_name = name.replace("-", "_").lower()
    app_id = f"{config['namespace']}.{sanitized_name}"

    # Build permissions XML from config + caller list
    all_permissions = list(config.get("permissions", []))
    if permissions:
        for p in permissions:
            if p not in all_permissions:
                all_permissions.append(p)
    permissions_xml = "\n    ".join(
        f'<uses-permission android:name="{p}" />' for p in all_permissions
    )

    # Build the optional release signing config. When sign_config is the path to
    # a (gitignored) keystore.properties file, the staged app/build.gradle gets a
    # loader + signingConfigs.release block and the release build type references
    # it (signed release APK). When absent, the placeholders resolve to empty so
    # the release APK is unsigned.
    sign_loader, sign_decl, sign_ref = _build_sign_block(sign_config)

    replacements = {
        "__SBT_PROJECT_NAME__": name,
        "__SBT_NAMESPACE__": config["namespace"],
        "__SBT_NAMESPACE_JNI__": config["namespace"].replace(".", "_"),
        "__SBT_LOG_TAG__": project_name,
        "__SBT_APP_ID__": app_id,
        "__SBT_APP_LABEL__": name,
        "__SBT_LIB_NAME__": sanitized_name,
        "__SBT_ABI__": abi,
        "__SBT_PERMISSIONS__": permissions_xml,
        "__SBT_NDK_VERSION__": ndk_version or "",
        "__SBT_KEYSTORE_LOADER__": sign_loader,
        "__SBT_SIGN_DECL__": sign_decl,
        "__SBT_SIGN_REF__": sign_ref,
    }

    for root, dirs, files in os.walk(staging_dir):
        for f in files:
            filepath = os.path.join(root, f)
            _replace_placeholders(filepath, replacements)

    # Point Gradle's local build cache at the build tree so it is wiped with the
    # build. This is injected here (not from the static template) so it never
    # produces invalid `directory = ""` when no cache dir is supplied.
    if gradle_cache_dir:
        _inject_build_cache_dir(os.path.join(staging_dir, "settings.gradle"),
                                os.path.join(gradle_cache_dir, "build-cache"))

    return config


def _inject_build_cache_dir(settings_path, cache_dir):
    """Insert a `buildCache { local { directory = ... } }` block into settings.gradle."""
    try:
        with open(settings_path, 'r') as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return
    # Escape for a single-quoted Groovy string literal.
    groovy_dir = cache_dir.replace("\\", "\\\\").replace("'", "\\'")
    block = (
        "\n// sbt: keep the Gradle build cache inside the build tree "
        "(wiped by `make clean`).\n"
        "buildCache {\n"
        "    local {\n"
        f"        directory = '{groovy_dir}'\n"
        "    }\n"
        "}\n"
    )
    # Insert before rootProject.name to keep `include ':app'` last.
    marker = "rootProject.name"
    if marker in content:
        content = content.replace(marker, block + marker, 1)
    else:
        content += block
    with open(settings_path, 'w') as f:
        f.write(content)


def _build_sign_block(sign_config):
    """Return (keystore loader, signingConfigs decl, release buildType ref).

    `sign_config` is the path to a `keystore.properties` file (relative to the
    project root, or absolute). The file must define `storeFile`, `storePassword`,
    `keyAlias` and `keyPassword`. Secrets are never written into the staged
    build.gradle: the loader reads them from the file at Gradle configure time,
    so they stay out of version control (gitignore the properties file). When
    sign_config is absent/empty, all three strings are empty and the release APK
    is left unsigned.
    """
    if not isinstance(sign_config, str) or not sign_config.strip():
        return "", "", ""
    props_path = os.path.abspath(sign_config.strip())
    if not os.path.isfile(props_path):
        raise ValueError(
            f"sbt: android_sign_config points to a missing keystore properties "
            f"file: {props_path}.\nCreate it (and gitignore it) with "
            "storeFile/storePassword/keyAlias/keyPassword, e.g.:\n"
            "    storeFile=keystores/release.keystore\n"
            "    storePassword=<pwd>\n"
            "    keyAlias=release\n"
            "    keyPassword=<pwd>\n"
        )
    required = ["storeFile", "storePassword", "keyAlias", "keyPassword"]
    props = {}
    try:
        with open(props_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    props[k.strip()] = v.strip()
    except OSError as e:
        raise ValueError(f"sbt: failed to read android_sign_config file {props_path}: {e}")
    missing = [k for k in required if not props.get(k)]
    if missing:
        raise ValueError(
            f"sbt: {props_path} is missing required keystore properties: "
            f"{', '.join(missing)}"
        )

    def _g(v):
        v = "" if v is None else str(v)
        # Escape backslash and single quote for a single-quoted Groovy literal.
        return v.replace("\\", "\\\\").replace("'", "\\'")

    loader = (
        "def keystorePropertiesFile = file('" + _g(props_path) + "')\n"
        "def keystoreProperties = new Properties()\n"
        "keystoreProperties.load(new FileInputStream(keystorePropertiesFile))"
    )
    # storeFile is resolved relative to the properties file's directory, so the
    # keystore path in keystore.properties behaves predictably regardless of the
    # (freshly re-created) staging dir.
    decl = (
        "signingConfigs {\n"
        "        release {\n"
        "            storeFile file(new File(keystorePropertiesFile.parentFile, keystoreProperties['storeFile']))\n"
        "            storePassword keystoreProperties['storePassword']\n"
        "            keyAlias keystoreProperties['keyAlias']\n"
        "            keyPassword keystoreProperties['keyPassword']\n"
        "        }\n"
        "    }"
    )
    ref = "signingConfig signingConfigs.release"
    return loader, decl, ref


def copy_so_to_jnilibs(staging_dir, so_path, lib_name):
    """Copy the built .so into the staged Gradle project's jniLibs.

    `lib_name` is the sanitized demo/bin name; the destination is always
    `lib{lib_name}.so` (the name TerminalActivity passes to System.loadLibrary).
    """
    abi = get_abi()
    jnilibs_dir = os.path.join(staging_dir, "app", "src", "main", "jniLibs", abi)
    os.makedirs(jnilibs_dir, exist_ok=True)
    dst = os.path.join(jnilibs_dir, f"lib{lib_name}.so")
    shutil.copy2(str(so_path), dst)
    return dst


def collect_module_sos(build_lib_path, libs):
    """Return the shared-lib paths of the sbt module libs referenced by `libs`.

    Filters `libs` down to the entries that resolve to an existing
    `lib<name>.so` under `build_lib_path`. These are exactly the sbt module
    libraries (including the transitive deps already folded into LIBS by
    create_module_env); system/extlibs (android, log, GL, GLESv3, ...) live
    outside the sbt lib dir and are dropped. Used to bundle the module .so
    beside the entry .so in a shared (non-static) Android APK.
    """
    module_sos = []
    for lib in libs:
        if not isinstance(lib, str):
            continue
        so_path = os.path.join(build_lib_path, f"lib{lib}.so")
        if os.path.isfile(so_path):
            module_sos.append(so_path)
    return module_sos


def copy_module_sos_to_jnilibs(staging_dir, module_sos):
    """Copy every module shared lib into jniLibs, preserving its .so basename.

    Android's app namespace resolves DT_NEEDED against the extracted native
    library dir, so bundling each `lib<sihd>_<mod>.so` here (beside the entry
    .so) is all the dynamic linker needs to load the module chain when
    System.loadLibrary(entry) runs. Missing files are skipped so a module that
    was built static or excluded doesn't fail the APK build.
    """
    if not module_sos:
        return []
    abi = get_abi()
    jnilibs_dir = os.path.join(staging_dir, "app", "src", "main", "jniLibs", abi)
    os.makedirs(jnilibs_dir, exist_ok=True)
    dsts = []
    for so_path in module_sos:
        src = str(so_path)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(jnilibs_dir, os.path.basename(src))
        shutil.copy2(src, dst)
        dsts.append(dst)
    return dsts


def stage_bridge_source(dst_path, namespace, log_tag):
    """Write terminal_bridge.cpp to dst_path with placeholders replaced.

    The bridge is compiled into the SharedLibrary by scons, so its JNI symbol
    name (Java_<namespace>_TerminalActivity_nativeMain) and log tag must be
    resolved before compilation, not at gradle staging time.
    """
    src = os.path.join(TEMPLATE_DIR, "app", "src", "main", "cpp", "terminal_bridge.cpp")
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    with open(src) as f:
        content = f.read()
    content = content.replace("__SBT_NAMESPACE_JNI__", namespace.replace(".", "_"))
    content = content.replace("__SBT_LOG_TAG__", log_tag)
    with open(dst_path, "w") as f:
        f.write(content)
    return dst_path


def build_apk(staging_dir, apk_output_path, build_type="debug", gradle_cache_dir=None, apk_name=None):
    """Run gradle assemble<BuildType> and copy the APK to the output path.

    Args:
        staging_dir: staged Gradle project directory
        apk_output_path: destination path for the built APK
        build_type: Gradle build type ("debug" or "release", etc.); appended to
            `assemble`. Build types mapped from release-like sbt modes produce
            the stripped APK (e.g. assembleRelease).
        gradle_cache_dir: base dir for the Gradle caches for this build
            configuration (a sibling of `lib/`/`demo/`): the shared local
            build-cache (`build-cache/`) is injected into the staged
            settings.gradle and lives here. It is inside the build tree and is
            wiped by `make clean`, and survives the staging dir being rebuilt.
            When None, no cache relocation is configured.
        apk_name: the APK name used to scope this build's own `.gradle` project
            cache under gradle_cache_dir. Each APK gets its own `.gradle` so that
            parallel `assemble` invocations (different APKs, e.g. under `-j`) do
            not contend on Gradle's single-writer locks (notably the
            configuration cache). The heavier build cache and dependency cache
            remain shared across APKs of the configuration.
    Returns 0 on success, non-zero on failure.
    """
    gradle_env = os.environ.copy()
    gradle_env["ANDROID_SDK_PATH"] = builder.get_android_sdk_root()
    java_home = builder.get_java_home()
    if java_home:
        gradle_env["JAVA_HOME"] = java_home

    project_cache_dir = None
    if gradle_cache_dir:
        os.makedirs(gradle_cache_dir, exist_ok=True)
        # Per-APK project cache: each APK is a separate Gradle project and uses
        # its own `.gradle`, so parallel APK builds don't fight over the
        # configuration-cache lock (the shared build-cache stays concurrency-safe).
        if apk_name:
            project_cache_dir = os.path.join(gradle_cache_dir, apk_name, ".gradle")
            os.makedirs(project_cache_dir, exist_ok=True)

    logger.info(f"building APK: {os.path.basename(apk_output_path)} ({build_type})")
    cmd = ["gradle", f"assemble{build_type.capitalize()}"]
    if project_cache_dir:
        cmd += ["--project-cache-dir", project_cache_dir]
    ret = subprocess.call(cmd, cwd=staging_dir, env=gradle_env)
    if ret != 0:
        logger.error(f"gradle assemble{build_type.capitalize()} failed")
        return ret

    gradle_apks = glob.glob(os.path.join(
        staging_dir, "app", "build", "outputs", "apk", build_type, "*.apk"
    ))
    if not gradle_apks:
        logger.error(f"APK not found under app/build/outputs/apk/{build_type}")
        return 1

    os.makedirs(os.path.dirname(apk_output_path), exist_ok=True)
    shutil.copy2(gradle_apks[0], apk_output_path)
    logger.info(f"APK built: {apk_output_path}")
    return 0
