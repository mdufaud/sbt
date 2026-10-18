#!/usr/bin/env python3
"""
Usage: run_cppcheck.py <BUILD_PATH> <PROJECT_ROOT_PATH> [module1 module2 ...]

Runs cppcheck on the specified modules (or all if none given).
Configuration is read from app.py, in two layers with the same keys — a
top-level `cppcheck` dict for the whole project, and `cppcheck-*` keys in
each module's conf for per-subproject overrides:

    cppcheck = {
        "std":        "c++17",        # --std= — NO default (cppcheck picks
                                      #   the language from file extensions
                                      #   and its own default standard)
        "language":   "c++",          # --language= — NO default
        "enable":     ["warning", "style"],   # REPLACES the default check set
        "suppresses": ["uninitvar"],  # extra --suppress=
        "defines":    ["FOO=1"],      # extra -D ("-D" prefix optional)
        "undefines":  ["BAR"],        # extra -U ("-U" prefix optional)
        "includes":   ["/usr/include/python3.12"],  # extra -I
        "args":       ["--addon=misra;misc.config"],  # raw args, verbatim
    }

    "mymodule": {
        "cppcheck-skip":       True,    # exclude module entirely
        "cppcheck-std":        "c++23", # ...and the same keys as the global
        "cppcheck-language":   "c++",   #     dict, prefixed with "cppcheck-"
        "cppcheck-enable":     ["all"],
        "cppcheck-suppresses": ["uninitvar"],
        "cppcheck-defines":    ["FOO=1"],
        "cppcheck-undefines":  ["BAR"],
        "cppcheck-includes":   ["/usr/include/python3.12"],
        "cppcheck-args":       ["--addon=threads"],
    }

Resolution, per module: built-in defaults < global `cppcheck` < module
`cppcheck-*`. `enable` replaces the check set at each layer; the other list
keys (suppresses/defines/undefines/includes/args) accumulate. Raw `args` land
at the end of the command line verbatim, and cppcheck takes value flags
(--std, --language, --platform, --template, --error-exitcode,
--cppcheck-build-dir, -j) from their LAST occurrence — duplicates from the
layers above are pruned, so `args` (and module keys over global ones) win
without surprises.

Output per module:
    <BUILD_PATH>/cppcheck/<module>/report.xml
    <BUILD_PATH>/cppcheck/<module>/stdout.txt
    <BUILD_PATH>/cppcheck/<module>/html/index.html  (requires cppcheck-htmlreport)

Global error report (severity=error only):
    <BUILD_PATH>/cppcheck/errors.xml
    <BUILD_PATH>/cppcheck/html/index.html           (requires cppcheck-htmlreport)
"""

import json
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
from sbt.build import modules as sbt_modules

_BASE_SUPPRESSES = [
    "missingInclude",
    "missingIncludeSystem",
    "unusedFunction",
    "unusedStructMember",
    "unknownMacro",
]

_DEFAULT_ENABLE = ["warning", "style", "performance", "portability"]

# Flags whose value cppcheck takes from the LAST occurrence on the command
# line. The command is layered (defaults < global config < module config <
# raw args) then pruned on these, so a later layer overrides without leaving
# shadow copies behind.
_SINGLETON_FLAGS = frozenset([
    "--std",
    "--language",
    "--platform",
    "--template",
    "--error-exitcode",
    "--cppcheck-build-dir",
    "-j",
])


def _as_list(value) -> list:
    """Config tolerance: accept a scalar or a list where a list is expected."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _prefixed(prefix: str, value: str) -> str:
    return value if value.startswith(prefix) else f"{prefix}{value}"


def _flag_name(arg: str) -> str | None:
    """Singleton flag carried by arg, or None. Matches the attached value
    forms ('--std=c++17', '-j4') and the separate one ('--std', 'c++17')."""
    if arg.startswith("--"):
        name = arg.partition("=")[0]
        return name if name in _SINGLETON_FLAGS else None
    if arg.startswith("-j"):
        return "-j"
    return None


def _flag_value_attached(arg: str) -> bool:
    if arg.startswith("-j"):
        return len(arg) > 2
    return "=" in arg


def _dedupe_singleton_flags(cmd: list[str]) -> list[str]:
    """Keep only the last occurrence of each singleton flag (and its separate
    value token) — cppcheck honours the last occurrence."""
    last: dict[str, int] = {}
    for i, arg in enumerate(cmd):
        name = _flag_name(arg)
        if name is not None:
            last[name] = i
    drop: set[int] = set()
    for i, arg in enumerate(cmd):
        name = _flag_name(arg)
        if name is None or last[name] == i:
            continue
        drop.add(i)
        if not _flag_value_attached(arg):
            drop.add(i + 1)
    return [arg for i, arg in enumerate(cmd) if i not in drop]


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
    ]

    enable = mod_conf.get("cppcheck-enable") or global_conf.get("enable") or _DEFAULT_ENABLE
    cmd.append(f"--enable={','.join(_as_list(enable))}")

    # No --std/--language by default: forcing c++20 misdetects modules written
    # for another standard (or plain C). Letting cppcheck infer per file is the
    # safe baseline; projects opt in explicitly when they know better.
    std = mod_conf.get("cppcheck-std") or global_conf.get("std")
    if std:
        cmd.append(f"--std={std}")
    language = mod_conf.get("cppcheck-language") or global_conf.get("language")
    if language:
        cmd.append(f"--language={language}")

    cmd += [
        "--inline-suppr",
        "--quiet",
        "--error-exitcode=1",
        "--xml",
    ]

    # raw escape hatch, verbatim — last occurrence wins for singleton flags
    cmd += _as_list(global_conf.get("args")) + _as_list(mod_conf.get("cppcheck-args"))

    suppresses = _BASE_SUPPRESSES + \
        _as_list(global_conf.get("suppresses")) + \
        _as_list(mod_conf.get("cppcheck-suppresses"))
    for s in suppresses:
        cmd.append(f"--suppress={s}")
    undefines = _as_list(global_conf.get("undefines")) + \
        _as_list(mod_conf.get("cppcheck-undefines"))
    for u in undefines:
        cmd.append(_prefixed("-U", u.removeprefix("-U")))
    defines = _as_list(global_conf.get("defines")) + \
        _as_list(mod_conf.get("cppcheck-defines"))
    for d in defines:
        cmd.append(_prefixed("-D", d))
    cmd.append(f"-I{inc_dir}")
    includes = _as_list(global_conf.get("includes")) + \
        _as_list(mod_conf.get("cppcheck-includes"))
    for inc in includes:
        cmd.append(_prefixed("-I", inc))
    cmd.append(src_dir)
    return _dedupe_singleton_flags(cmd)


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
    modules_dir: str,
    cppcheck_dir: str,
    global_conf: dict,
    mod_conf: dict,
    have_html: bool,
) -> dict | None:
    src_dir = os.path.join(modules_dir, mod, "src")
    inc_dir = os.path.join(modules_dir, mod, "include")
    if not os.path.isdir(src_dir):
        return None

    mod_dir = os.path.join(cppcheck_dir, mod)
    os.makedirs(mod_dir, exist_ok=True)

    xml_out = os.path.join(mod_dir, "report.xml")
    txt_out = os.path.join(mod_dir, "stdout.txt")

    logger.info(f"running cppcheck on module: {mod}")

    sbt_incs = _sbt_includes()
    sbt_sup = _sbt_include_suppresses()
    merged_global = {
        **global_conf,
        "includes": _as_list(global_conf.get("includes")) + sbt_incs,
        "suppresses": _as_list(global_conf.get("suppresses")) + sbt_sup,
    }
    cmd = _build_cppcheck_cmd(src_dir, inc_dir, merged_global, mod_conf)
    with open(xml_out, "w") as xml_f, open(txt_out, "w") as txt_f:
        rc = subprocess.run(cmd, stdout=txt_f, stderr=xml_f).returncode

    try:
        issues = Path(xml_out).read_text().count("<error ")
    except OSError:
        issues = 0

    try:
        errors = sum(1 for e in ET.parse(xml_out).getroot().iter("error") if e.get("severity") == "error")
    except (OSError, ET.ParseError):
        errors = 0

    if issues > 0:
        logger.warning(f"Result: {issues} issue(s), {errors} error(s)")
    else:
        logger.info(f"Result: ok")

    if have_html:
        html_dir = os.path.join(mod_dir, "html")
        os.makedirs(html_dir, exist_ok=True)
        subprocess.run(
            ["cppcheck-htmlreport", "--title", mod,
             "--file", xml_out, "--report-dir", html_dir, "--source-dir", modules_dir],
            stderr=subprocess.DEVNULL,
        )

    return {"errors": errors, "issues": issues, "rc": rc, "report": xml_out}


def write_summary(cppcheck_dir: str, results: dict, threshold: int | None, rc: int) -> None:
    errors = sum(r["errors"] for r in results.values())
    issues = sum(r["issues"] for r in results.values())
    status = "failed" if rc != 0 else "passed"
    summary = {
        "modules": results,
        "errors": errors,
        "issues": issues,
        "threshold": threshold,
        "status": status,
    }
    with open(os.path.join(cppcheck_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if not step_summary:
        return
    lines = ["## cppcheck", "", "| module | errors | issues |", "| --- | ---: | ---: |"]
    lines += [f"| {mod} | {r['errors']} | {r['issues']} |" for mod, r in results.items()]
    lines += [
        f"| **total** | **{errors}** | **{issues}** |",
        "",
        f"threshold: {'unset' if threshold is None else threshold}",
        "",
        f"status: **{status}**",
        "",
    ]
    with open(step_summary, "a") as f:
        f.write("\n".join(lines) + "\n")


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
        modules_dir = builder.build_modules_path
        app_modules: dict = sbt_modules.get_module_merged_with_conditionals(app)
        global_cppcheck: dict = getattr(app, "cppcheck", {})
        fail_under: int | None = getattr(app, "cppcheck_fail_under", None)
    except Exception as exc:
        logger.warning(f"could not load app.py: {exc} — running without per-module config")
        modules_dir = project_root
        app_modules = {}
        global_cppcheck = {}
        fail_under = None

    if not modules:
        modules = sorted(
            d for d in os.listdir(modules_dir)
            if os.path.isfile(os.path.join(modules_dir, d, "scons.py"))
        )

    cppcheck_dir = os.path.join(build_path, "cppcheck")
    os.makedirs(cppcheck_dir, exist_ok=True)

    rc = 0
    ran: list[str] = []
    results: dict[str, dict] = {}

    for mod in modules:
        mod_conf = app_modules.get(mod, {})
        if mod_conf.get("cppcheck-skip", False):
            logger.info(f"skipping module: {mod} (cppcheck-skip)")
            continue
        res = run_module(mod, modules_dir, cppcheck_dir, global_cppcheck, mod_conf, have_html)
        if res is not None:
            results[mod] = res
            if res["rc"] != 0:
                rc = res["rc"]
        ran.append(mod)

    generate_global_report(ran, cppcheck_dir, project_root, have_html)
    print_reports(ran, cppcheck_dir, have_html)

    if fail_under is not None:
        errors = sum(r["errors"] for r in results.values())
        rc = 1 if errors > fail_under else 0
        if rc:
            logger.error(f"cppcheck failed: {errors} error(s) > cppcheck_fail_under={fail_under}")
        else:
            logger.info(f"cppcheck passed: {errors} error(s) <= cppcheck_fail_under={fail_under}")
    write_summary(cppcheck_dir, results, fail_under, rc)

    return rc


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <BUILD_PATH> <PROJECT_ROOT_PATH> [module ...]", file=sys.stderr)
        sys.exit(1)
    sys.exit(run(sys.argv[1], sys.argv[2], sys.argv[3:]))
