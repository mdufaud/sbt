#!/usr/bin/env python3
"""
Usage: run_cppcheck.py <BUILD_PATH> <PROJECT_ROOT_PATH> [module1 module2 ...]

Runs cppcheck on the specified modules (or all if none given).
Per-module configuration is read from app.py:

    "mymodule": {
        "cppcheck-skip":       True,           # exclude module entirely
        "cppcheck-suppresses": ["uninitvar"],   # extra --suppress=
        "cppcheck-defines":    ["-DFOO=1"],     # extra -D
        "cppcheck-undefines":  ["-UBAR"],       # extra -U
        "cppcheck-includes":   ["/usr/include/python3.12"],  # extra -I
    }

Global cppcheck config (top-level app.py dict):

    cppcheck = {
        "suppresses": [...],
        "undefines":  [...],
        "defines":    [...],
        "includes":   [...],
    }

Output per module:
    <BUILD_PATH>/cppcheck/<module>/report.xml
    <BUILD_PATH>/cppcheck/<module>/stdout.txt
    <BUILD_PATH>/cppcheck/<module>/html/index.html  (requires cppcheck-htmlreport)

Global error report (severity=error only):
    <BUILD_PATH>/cppcheck/errors.xml
    <BUILD_PATH>/cppcheck/html/index.html           (requires cppcheck-htmlreport)
"""

import os
import sys
import subprocess
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from multiprocessing import cpu_count

# site_scons/sbt/scripts/run_cppcheck.py -> site_scons (for `from sbt...` imports)
_site_scons = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
if _site_scons not in sys.path:
    sys.path.insert(0, _site_scons)

from sbt.core import loader
from sbt.core import builder
from sbt.core import logger
from site_scons.sbt.build import modules as sbt_modules

_BASE_SUPPRESSES = [
    "missingInclude",
    "missingIncludeSystem",
    "unusedFunction",
    "unusedStructMember",
    "unknownMacro",
]


def _merge_xml(output_path: str, input_paths: list[str]) -> None:
    """Merge multiple cppcheck XML v2 reports, keeping only severity=error entries."""
    errors: list[ET.Element] = []
    cppcheck_version = "unknown"

    for path in input_paths:
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as exc:
            logger.warning(f"could not parse {path}: {exc}")
            continue
        for el in root.iter("cppcheck"):
            cppcheck_version = el.get("version", cppcheck_version)
        for error in root.iter("error"):
            if error.get("severity") == "error":
                errors.append(error)

    results = ET.Element("results", {"version": "2"})
    ET.SubElement(results, "cppcheck", {"version": cppcheck_version})
    errors_el = ET.SubElement(results, "errors")
    for error in errors:
        errors_el.append(error)

    ET.indent(results)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write(ET.tostring(results, encoding="unicode"))
        f.write("\n")

    logger.info(f"merged {len(errors)} error(s) from {len(input_paths)} report(s) into {output_path}")


def _build_cppcheck_cmd(
    src_dir: str,
    inc_dir: str,
    global_conf: dict,
    mod_conf: dict,
) -> list[str]:
    cmd = [
        "cppcheck",
        f"-j{cpu_count()}",
        "--enable=warning,style,performance,portability",
        "--std=c++20",
        "--language=c++",
        "--inline-suppr",
        "--quiet",
        "--error-exitcode=1",
        "--xml",
    ]
    suppresses = _BASE_SUPPRESSES + global_conf.get("suppresses", []) + mod_conf.get("cppcheck-suppresses", [])
    for s in suppresses:
        cmd.append(f"--suppress={s}")
    undefines = [u.lstrip("-U") for u in global_conf.get("undefines", [])] + \
                [u.lstrip("-U") for u in mod_conf.get("cppcheck-undefines", [])]
    for u in undefines:
        cmd.append(f"-U{u}")
    defines = global_conf.get("defines", []) + mod_conf.get("cppcheck-defines", [])
    for d in defines:
        cmd.append(d if d.startswith("-D") else f"-D{d}")
    cmd.append(f"-I{inc_dir}")
    for inc in global_conf.get("includes", []) + mod_conf.get("cppcheck-includes", []):
        cmd.append(f"-I{inc}")
    cmd.append(src_dir)
    return cmd


def _sbt_includes() -> list[str]:
    """Return existing SBT canonical include dirs for cppcheck.

    Uses builder.py as the single source of truth:
        build_hdr_path        = $(BUILD_PATH)/include         # installed module headers
        build_extlib_hdr_path = $(BUILD_PATH)/extlib/include  # vcpkg_installed/<triplet>
    """
    candidates = [
        builder.build_hdr_path,
        builder.build_extlib_hdr_path,
    ]
    return [p for p in candidates if os.path.isdir(p)]


def _sbt_include_suppresses() -> list[str]:
    """Suppress cppcheck issues originating from SBT-managed external dirs.

    These dirs are added as -I for type resolution only — issues inside
    extlib (vcpkg) and the installed module headers must not be reported.
    """
    suppresses = []
    for path in _sbt_includes():
        suppresses.append(f"*:{path}/*")
    return suppresses


def run_module(
    mod: str,
    project_root: str,
    cppcheck_dir: str,
    global_conf: dict,
    mod_conf: dict,
    have_html: bool,
) -> int:
    src_dir = os.path.join(project_root, mod, "src")
    inc_dir = os.path.join(project_root, mod, "include")
    if not os.path.isdir(src_dir):
        return 0

    mod_dir = os.path.join(cppcheck_dir, mod)
    os.makedirs(mod_dir, exist_ok=True)

    xml_out = os.path.join(mod_dir, "report.xml")
    txt_out = os.path.join(mod_dir, "stdout.txt")

    logger.info(f"running cppcheck on module: {mod}")

    sbt_incs = _sbt_includes()
    sbt_sup = _sbt_include_suppresses()
    merged_global = {
        **global_conf,
        "includes": global_conf.get("includes", []) + sbt_incs,
        "suppresses": global_conf.get("suppresses", []) + sbt_sup,
    }
    cmd = _build_cppcheck_cmd(src_dir, inc_dir, merged_global, mod_conf)
    with open(xml_out, "w") as xml_f, open(txt_out, "w") as txt_f:
        rc = subprocess.run(cmd, stdout=txt_f, stderr=xml_f).returncode

    try:
        issues = Path(xml_out).read_text().count("<error ")
    except OSError:
        issues = 0

    if issues > 0:
        logger.warning(f"Result: {issues} issue(s)")
    else:
        logger.info(f"Result: ok")

    if have_html:
        html_dir = os.path.join(mod_dir, "html")
        os.makedirs(html_dir, exist_ok=True)
        subprocess.run(
            ["cppcheck-htmlreport", "--title", mod,
             "--file", xml_out, "--report-dir", html_dir, "--source-dir", project_root],
            stderr=subprocess.DEVNULL,
        )

    return rc


def generate_global_report(
    modules: list[str],
    cppcheck_dir: str,
    project_root: str,
    have_html: bool,
) -> None:
    xml_files = [
        os.path.join(cppcheck_dir, mod, "report.xml")
        for mod in modules
        if os.path.isfile(os.path.join(cppcheck_dir, mod, "report.xml"))
    ]
    if not xml_files:
        return

    global_xml = os.path.join(cppcheck_dir, "errors.xml")
    _merge_xml(global_xml, xml_files)

    if have_html:
        html_dir = os.path.join(cppcheck_dir, "html")
        os.makedirs(html_dir, exist_ok=True)
        subprocess.run(
            ["cppcheck-htmlreport", "--title", "all modules - errors",
             "--file", global_xml, "--report-dir", html_dir, "--source-dir", project_root],
            stderr=subprocess.DEVNULL,
        )


def print_reports(modules: list[str], cppcheck_dir: str, have_html: bool) -> None:
    global_html = os.path.join(cppcheck_dir, "html", "index.html")
    if os.path.isfile(global_html):
        logger.info(f"global report: {global_html}")
    for mod in modules:
        mod_dir = os.path.join(cppcheck_dir, mod)
        if not os.path.isdir(mod_dir):
            continue
        html = os.path.join(mod_dir, "html", "index.html")
        xml = os.path.join(mod_dir, "report.xml")
        if have_html and os.path.isfile(html):
            logger.info(f"{mod}: {html}")
        elif os.path.isfile(xml):
            logger.info(f"{mod}: {xml}")


def run(
    build_path: str,
    project_root: str,
    modules: list[str],
) -> int:
    if not shutil.which("cppcheck"):
        logger.error("cppcheck not found - install with your package manager")
        return 1

    have_html = bool(shutil.which("cppcheck-htmlreport"))

    try:
        app = loader.load_app()
        app_modules: dict = sbt_modules.get_module_merged_with_conditionals(app)
        global_cppcheck: dict = getattr(app, "cppcheck", {})
    except Exception as exc:
        logger.warning(f"could not load app.py: {exc} — running without per-module config")
        app_modules = {}
        global_cppcheck = {}

    if not modules:
        modules = sorted(
            d for d in os.listdir(project_root)
            if os.path.isfile(os.path.join(project_root, d, "scons.py"))
        )

    cppcheck_dir = os.path.join(build_path, "cppcheck")
    os.makedirs(cppcheck_dir, exist_ok=True)

    rc = 0
    ran: list[str] = []

    for mod in modules:
        mod_conf = app_modules.get(mod, {})
        if mod_conf.get("cppcheck-skip", False):
            logger.info(f"skipping module: {mod} (cppcheck-skip)")
            continue
        ret = run_module(mod, project_root, cppcheck_dir, global_cppcheck, mod_conf, have_html)
        if ret != 0:
            rc = ret
        ran.append(mod)

    generate_global_report(ran, cppcheck_dir, project_root, have_html)
    print_reports(ran, cppcheck_dir, have_html)

    return rc


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <BUILD_PATH> <PROJECT_ROOT_PATH> [module ...]", file=sys.stderr)
        sys.exit(1)
    sys.exit(run(sys.argv[1], sys.argv[2], sys.argv[3:]))
