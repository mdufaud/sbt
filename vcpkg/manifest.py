"""
vcpkg manifest building.

Handles:
  - Building the vcpkg.json manifest from module dependencies
  - Writing manifest to disk
  - Building the cross-linux foundation manifest (X11/Wayland first-pass)
"""

import os
from json import dump as json_dump

from sbt.core import builder
from sbt.core import logger

# Single source of truth for the default vcpkg baseline commit hash.
# app.py can override this via `vcpkg_baseline = "..."`.
_DEFAULT_VCPKG_BASELINE = "3a3285c4878c7f5a957202201ba41e6fdeba8db4"


def _get_baseline(app) -> str:
    """Return the vcpkg baseline from app config, or the built-in default."""
    return getattr(app, "vcpkg_baseline", _DEFAULT_VCPKG_BASELINE)


def _add_dependency(manifest: dict, name: str, version: str, features_map: dict = None):
    """
    Add a single dependency to a vcpkg manifest dict.
    Handles features lookup and version overrides.
    """
    if features_map is None:
        features_map = {}
    dep = {"name": name}
    if name in features_map:
        dep["features"] = features_map[name]
    # Use dict form if we have more than just the name
    if len(dep) > 1:
        manifest["dependencies"].append(dep)
    else:
        manifest["dependencies"].append(name)
    if version:
        manifest["overrides"].append({
            "name": name,
            "version": version,
        })


def _new_manifest(app) -> dict:
    """Create an empty vcpkg manifest with the baseline set."""
    return {
        "builtin-baseline": _get_baseline(app),
        "dependencies": [],
        "overrides": [],
    }


def build_vcpkg_manifest(app, extlibs: dict, needs_display_libs: bool = False) -> dict:
    """
    Build the vcpkg manifest dict from the app configuration and resolved extlibs.
    """
    vcpkg_manifest = _new_manifest(app)

    features = dict(getattr(app, "extlibs_features", {}))
    # Platform-specific features (e.g. imgui[android-binding] on android, libusb[udev] on linux).
    # Skipped only for cross-linux builds (no system X11/Wayland libs available).
    is_cross_linux = builder.is_cross_building() and builder.build_platform == "linux"
    if not is_cross_linux:
        platform_features = getattr(app, f"extlibs_features_{builder.build_platform}", {})
        for name, feature_list in platform_features.items():
            features[name] = feature_list

    # Libraries for which vcpkg default-features should be disabled (e.g. when cross-compiling)
    # This also adds the library to the manifest if it's not already there (transitive dep override)
    no_default_features = set()
    if builder.is_cross_building():
        skip_libs = set(getattr(app, "extlibs_skip", []))
        skip_libs |= set(getattr(app, f"extlibs_skip_{builder.build_platform}", []))
        no_default_features = set(getattr(app, "vcpkg_no_default_features", [])) - skip_libs

    for libname, libversion in sorted(extlibs.items()):
        dep = {"name": libname}
        if libname in features:
            dep["features"] = features[libname]
        if libname in no_default_features:
            dep["default-features"] = False
            no_default_features.discard(libname)
        if len(dep) > 1:
            vcpkg_manifest["dependencies"].append(dep)
        else:
            vcpkg_manifest["dependencies"].append(libname)
        if libversion:
            vcpkg_manifest["overrides"].append({
                "name": libname,
                "version": libversion,
            })

    # Cross-linux: add X11/Wayland vcpkg packages (built from source for the target)
    # Only when the caller signals that display libs are needed.
    if builder.is_cross_building() and builder.build_platform == "linux" and needs_display_libs:
        cross_extlibs = getattr(app, "vcpkg_cross_linux_extlibs", {})
        cross_features = getattr(app, "vcpkg_cross_linux_extlibs_features", {})
        for libname, libversion in sorted(cross_extlibs.items()):
            _add_dependency(vcpkg_manifest, libname, libversion, cross_features)

    # Add remaining no_default_features libs that weren't in extlibs (transitive dep overrides)
    no_default_features_add = {}
    requires_map = {}
    if builder.is_cross_building():
        no_default_features_add = getattr(app, "vcpkg_no_default_features_add", {})
        requires_map = getattr(app, "vcpkg_no_default_features_requires", {})
    for name in no_default_features:
        # skip force-add unless a requirer is in the build (see vcpkg_no_default_features_requires)
        requirers = requires_map.get(name)
        if requirers is not None and not any(req in extlibs for req in requirers):
            continue
        dep = {"name": name, "default-features": False}
        dep_features = no_default_features_add.get(name, [])
        if name in features:
            dep_features = features[name] + dep_features
        if dep_features:
            dep["features"] = dep_features
        vcpkg_manifest["dependencies"].append(dep)

    return vcpkg_manifest


def write_vcpkg_manifest(manifest_path: str, vcpkg_manifest: dict):
    """Write the vcpkg manifest dict to a file."""
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    with open(manifest_path, "w") as fd:
        json_dump(vcpkg_manifest, fd, indent=2)
    logger.info(f"wrote vcpkg manifest at: {manifest_path}")


def build_cross_linux_foundation_manifest(app) -> dict:
    """
    Build a minimal manifest containing only X11/Wayland foundation packages.
    These must be installed BEFORE the main manifest because ports like glfw3/sdl3
    use cmake's FindX11/FindWayland to locate them at configure time, but don't
    declare vcpkg dependencies on them (they expect system packages).
    """
    manifest = _new_manifest(app)
    cross_extlibs = getattr(app, "vcpkg_cross_linux_extlibs", {})
    cross_features = getattr(app, "vcpkg_cross_linux_extlibs_features", {})

    for libname, libversion in cross_extlibs.items():
        _add_dependency(manifest, libname, libversion, cross_features)

    return manifest
