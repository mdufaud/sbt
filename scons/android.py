"""
Android APK build helper for sbt.

Provides functions to stage a Gradle project from templates,
replace placeholders, build a SharedLibrary, and package an APK.
"""

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


def stage_gradle_project(staging_dir, name, module_android_dir=None, permissions=None, project_name=None):
    """Stage a complete Gradle project from templates + optional overrides.

    Args:
        staging_dir: where to create the Gradle project
        name: demo/bin name (used for placeholders)
        module_android_dir: optional module-relative android/ override directory
        permissions: list of Android permission strings (e.g. ["android.permission.INTERNET"])
        project_name: app name used to derive the default Java namespace
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
    }

    for root, dirs, files in os.walk(staging_dir):
        for f in files:
            filepath = os.path.join(root, f)
            _replace_placeholders(filepath, replacements)

    return config


def copy_so_to_jnilibs(staging_dir, so_path, lib_name):
    """Copy the built .so into the staged Gradle project's jniLibs."""
    abi = get_abi()
    jnilibs_dir = os.path.join(staging_dir, "app", "src", "main", "jniLibs", abi)
    os.makedirs(jnilibs_dir, exist_ok=True)
    dst = os.path.join(jnilibs_dir, f"lib{lib_name}.so")
    shutil.copy2(str(so_path), dst)
    return dst


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


def build_apk(staging_dir, apk_output_path):
    """Run gradle assembleDebug and copy the APK to the output path.

    Returns 0 on success, non-zero on failure.
    """
    gradle_env = os.environ.copy()
    gradle_env["ANDROID_SDK_PATH"] = builder.get_android_sdk_root()
    java_home = builder.get_java_home()
    if java_home:
        gradle_env["JAVA_HOME"] = java_home

    logger.info(f"building APK: {os.path.basename(apk_output_path)}")
    ret = subprocess.call(
        ["gradle", "assembleDebug"],
        cwd=staging_dir,
        env=gradle_env,
    )
    if ret != 0:
        logger.error("gradle assembleDebug failed")
        return ret

    gradle_apk = os.path.join(
        staging_dir, "app", "build", "outputs", "apk", "debug", "app-debug.apk"
    )
    if not os.path.isfile(gradle_apk):
        logger.error(f"APK not found: {gradle_apk}")
        return 1

    os.makedirs(os.path.dirname(apk_output_path), exist_ok=True)
    shutil.copy2(gradle_apk, apk_output_path)
    logger.info(f"APK built: {apk_output_path}")
    return 0
