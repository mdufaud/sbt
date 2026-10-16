"""CycloneDX SBOM for vcpkg ports installed by SBT.

Components come from the vcpkg status database (vcpkg_installed/vcpkg/status), licenses
from vcpkg/licenses.py. No hashes or CPE: vcpkg ports carry neither.
"""

import json
import os
from urllib.parse import quote

from sbt.vcpkg import licenses as vcpkg_licenses


def _read_installed_packages(vcpkg_installed_path: str, triplet: str) -> dict[str, str]:
    status_path = os.path.join(vcpkg_installed_path, "vcpkg", "status")
    try:
        with open(status_path, encoding="utf-8") as f:
            paragraphs = f.read().split("\n\n")
    except OSError:
        return {}
    packages = {}
    for paragraph in paragraphs:
        fields = {}
        for line in paragraph.splitlines():
            if line and not line[0].isspace() and ": " in line:
                key, value = line.split(": ", 1)
                fields[key] = value
        if "Feature" in fields or "Version" not in fields:
            continue
        if fields.get("Architecture") == triplet and fields.get("Status") == "install ok installed":
            packages[fields["Package"]] = fields["Version"]
    return packages


def _license_entry(spdx: str) -> list[dict]:
    if spdx == "unknown":
        return [{"license": {"name": "unknown"}}]
    if any(token in spdx for token in (" ", "(")):
        return [{"expression": spdx}]
    return [{"license": {"id": spdx}}]


def _purl(name: str, version: str) -> str:
    return f"pkg:generic/{quote(name, safe='')}@{quote(version, safe='')}"


def build_sbom(
    app_name: str,
    app_version: str,
    vcpkg_installed_path: str,
    triplet: str,
    overlay_ports_path: tuple[str, ...],
    vcpkg_ports_path: str,
) -> dict:
    packages = _read_installed_packages(vcpkg_installed_path, triplet)
    components = []
    for name, version in sorted(packages.items()):
        license_id = vcpkg_licenses.get_port_license(name, overlay_ports_path, vcpkg_ports_path)
        components.append({
            "type": "library",
            "bom-ref": _purl(name, version),
            "name": name,
            "version": version,
            "purl": _purl(name, version),
            "licenses": _license_entry(license_id),
            "properties": [{"name": "sbt:triplet", "value": triplet}],
        })
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {"type": "application", "name": app_name, "version": app_version},
        },
        "components": components,
    }


def dump_sbom(sbom: dict, output_path: str) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sbom, f, indent=2)
        f.write("\n")
