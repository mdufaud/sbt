"""vcpkg license scanner for SBT.

Reads installed port metadata to collect SPDX license identifiers.
Source priority: overlay-ports vcpkg.json > vcpkg ports dir vcpkg.json > "unknown"
"""

import json
import os
import sys

# Strong copyleft: all linked/derived code must be released under the same license.
_STRONG_COPYLEFT: set[str] = {
    "AGPL-1.0", "AGPL-3.0",
    "GPL-2.0", "GPL-3.0",
}

# Weak copyleft: only modifications to the library itself must be released.
_WEAK_COPYLEFT: set[str] = {
    "CDDL-1.0",
    "EPL-1.0", "EPL-2.0",
    "EUPL-1.1", "EUPL-1.2",
    "LGPL-2.0", "LGPL-2.1", "LGPL-3.0",
    "MPL-2.0",
    "OSL-3.0",
}


def _single_license_level(spdx: str) -> str | None:
    """Return 'strong', 'weak', or None for a single SPDX identifier."""
    upper = spdx.upper()
    for keyword in _STRONG_COPYLEFT:
        if keyword.upper() in upper:
            return "strong"
    for keyword in _WEAK_COPYLEFT:
        if keyword.upper() in upper:
            return "weak"
    return None


def _copyleft_level(spdx: str) -> str | None:
    """Return 'strong', 'weak', or None.

    For compound expressions (e.g. 'BSD-3-Clause OR GPL-2.0-only'), only warn
    when *all* alternatives are copyleft — if at least one permissive option
    exists the user can legally choose that one.
    """
    parts = [p.strip() for p in spdx.replace("(", "").replace(")", "").split(" OR ")]
    if len(parts) > 1:
        levels = [_single_license_level(p) for p in parts]
        if all(lv is None for lv in levels):
            return None
        if any(lv is None for lv in levels):
            # At least one permissive alternative → not contaminating
            return None
        # All alternatives are copyleft: return the strongest one found
        if any(lv == "strong" for lv in levels):
            return "strong"
        return "weak"
    return _single_license_level(spdx)


def get_installed_ports(vcpkg_installed_path: str, triplet: str) -> list[str]:
    """Return sorted list of port names installed for the given triplet."""
    share_path = os.path.join(vcpkg_installed_path, triplet, "share")
    if not os.path.isdir(share_path):
        return []
    return sorted(entry.name for entry in os.scandir(share_path) if entry.is_dir())


def get_port_license(
    port_name: str,
    overlay_ports_path: str,
    vcpkg_ports_path: str,
) -> str:
    """Return SPDX license identifier for a port, or 'unknown'."""
    for search_dir in (overlay_ports_path, vcpkg_ports_path):
        if not search_dir:
            continue
        vcpkg_json = os.path.join(search_dir, port_name, "vcpkg.json")
        if os.path.isfile(vcpkg_json):
            try:
                with open(vcpkg_json, encoding="utf-8") as f:
                    data = json.load(f)
                license_val = data.get("license")
                if license_val:
                    return license_val
            except (OSError, json.JSONDecodeError):
                pass
    return "unknown"


def collect_licenses(
    vcpkg_installed_path: str,
    triplet: str,
    overlay_ports_path: str,
    vcpkg_ports_path: str,
) -> dict[str, str]:
    """Return mapping of port name → SPDX license for all installed ports."""
    ports = get_installed_ports(vcpkg_installed_path, triplet)
    return {
        port: get_port_license(port, overlay_ports_path, vcpkg_ports_path)
        for port in ports
    }


def dump_licenses(port_licenses: dict[str, str], output_path: str | None = None) -> None:
    """Print JSON report (lib_to_license + license_to_libs) and warn on copyleft libs."""
    if not port_licenses:
        print("(no installed ports found)")
        return

    lib_to_license: dict[str, str] = dict(sorted(port_licenses.items()))

    license_to_libs: dict[str, list[str]] = {}
    for lib, lic in lib_to_license.items():
        license_to_libs.setdefault(lic, []).append(lib)
    license_to_libs = dict(sorted(license_to_libs.items()))

    report = {
        "lib_to_license": lib_to_license,
        "license_to_libs": license_to_libs,
    }

    output = json.dumps(report, indent=2)
    print(output)

    for lib, lic in lib_to_license.items():
        level = _copyleft_level(lic)
        if level == "strong":
            print(
                f"WARNING: {lib} ({lic}) — strong copyleft: all linked/derived code must be released under the same license",
                file=sys.stderr,
            )
        elif level == "weak":
            print(
                f"WARNING: {lib} ({lic}) — weak copyleft: modifications to this library must be released",
                file=sys.stderr,
            )

    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(output)
            f.write("\n")
