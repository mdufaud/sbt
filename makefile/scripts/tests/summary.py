"""Write the test-run summary and print the end-of-run recap.

Usage: summary.py TEST_PATH APP_NAME [module ...]
Env: FAILED_MODULES (modules the executor flagged: exit code or sanitizer),
TEST_MODULE_REPORTS (0 drops per-module gtest xml once merged),
VERBOSE (non-zero lists passed tests in the recap too),
GITHUB_STEP_SUMMARY (markdown recap appended when set).
Writes TEST_PATH/summary.json and TEST_PATH/report.xml (merged gtest xml).
"""
import glob
import json
import os
import shutil
import sys
import xml.etree.ElementTree as ET


def read_exit_code(log_dir):
    try:
        with open(os.path.join(log_dir, "exit_code")) as f:
            return int(f.read().strip())
    except (ValueError, OSError):
        return None


def case_status(case):
    if case.find("failure") is not None or case.find("error") is not None:
        return "failed"
    if case.find("skipped") is not None or case.get("result") in ("skipped", "suppressed") \
            or case.get("status") == "notrun":
        return "skipped"
    return "passed"


def merge_shard_reports(test_path, app_name, module):
    shard_dir = os.path.join(test_path, "reports", "shards", module)
    if not os.path.isdir(shard_dir):
        return
    suites = []
    for report in sorted(glob.glob(os.path.join(shard_dir, "*", "*.xml"))):
        try:
            suites += list(ET.parse(report).getroot().iter("testsuite"))
        except (OSError, ET.ParseError):
            pass
    if suites:
        root = ET.Element("testsuites")
        root.extend(suites)
        ET.ElementTree(root).write(
            os.path.join(test_path, "reports", "{}_{}.xml".format(app_name, module)),
            encoding="utf-8", xml_declaration=True)
    shutil.rmtree(shard_dir)
    try:
        os.rmdir(os.path.dirname(shard_dir))
    except OSError:
        pass


def parse_report(path):
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return None, None
    cases = []
    for case in root.iter("testcase"):
        cases.append({
            "name": "{}.{}".format(case.get("classname", ""), case.get("name", "")),
            "time": float(case.get("time") or 0),
            "status": case_status(case),
        })
    return root, cases


def count(cases):
    return {
        "total": len(cases),
        "passed": sum(1 for c in cases if c["status"] == "passed"),
        "failed": sum(1 for c in cases if c["status"] == "failed"),
        "skipped": sum(1 for c in cases if c["status"] == "skipped"),
        "time": round(sum(c["time"] for c in cases), 3),
    }


def write_merged(path, app_name, suites, totals):
    root = ET.Element("testsuites", {
        "name": app_name,
        "tests": str(totals["total"]),
        "failures": str(totals["failed"]),
        "skipped": str(totals["skipped"]),
        "errors": "0",
        "time": "{:.3f}".format(totals["time"]),
    })
    root.extend(suites)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


class Colors:
    def __init__(self, enabled):
        self.red = "\033[0;31m" if enabled else ""
        self.green = "\033[0;32m" if enabled else ""
        self.yellow = "\033[0;33m" if enabled else ""
        self.reset = "\033[0m" if enabled else ""


def print_recap(modules, totals, failed_tests, skipped_tests, verbose):
    c = Colors(sys.stdout.isatty())
    label = {
        "passed": c.green + "OK     " + c.reset,
        "failed": c.red + "FAILED " + c.reset,
        "skipped": c.yellow + "SKIPPED" + c.reset,
    }
    width = max(len(module) for module in modules)
    print("")
    print("==================== TEST RESULTS ====================")
    for module, info in modules.items():
        color = c.red if info["status"] == "failed" else c.green
        if info["tests"] is None:
            print("{}{:<{}}{}  no report (exit {})".format(
                color, module, width, c.reset, info["exit_code"]))
            continue
        t = info["tests"]
        print("{}{:<{}}{}  {:>5} tests  {:>4} skipped  {:>4} failed  {:>8.3f} s".format(
            color, module, width, c.reset, t["total"], t["skipped"], t["failed"], t["time"]))
        for case in info["cases"]:
            if verbose or case["status"] != "passed":
                print("  {} {:8.3f} s  {}".format(label[case["status"]], case["time"], case["name"]))
    print("------------------------------------------------------")
    color = c.red if totals["failed"] or failed_tests else c.green
    print("{}total: {} tests, {} passed, {} failed, {} skipped, {:.3f} s{}".format(
        color, totals["total"], totals["passed"], totals["failed"], totals["skipped"],
        totals["time"], c.reset))
    if failed_tests:
        print("failed:")
        width = max(len(f["module"]) for f in failed_tests)
        for f in failed_tests:
            print("  {}{:<{}}  {}{}".format(c.red, f["module"], width, f["test"], c.reset))
    print("======================================================")


def write_step_summary(path, app_name, modules, totals, failed_tests, skipped_tests):
    lines = [
        "## Tests: {}".format(app_name),
        "",
        "| Module | Status | Tests | Failed | Skipped | Time (s) |",
        "|---|---|---|---|---|---|",
    ]
    for module, info in modules.items():
        t = info["tests"]
        if t is None:
            lines.append("| {} | {} | - | - | - | - |".format(module, info["status"]))
        else:
            lines.append("| {} | {} | {} | {} | {} | {:.3f} |".format(
                module, info["status"], t["total"], t["failed"], t["skipped"], t["time"]))
    lines += [
        "",
        "**Total**: {} tests, {} passed, {} failed, {} skipped, {:.3f} s".format(
            totals["total"], totals["passed"], totals["failed"], totals["skipped"], totals["time"]),
    ]
    if failed_tests:
        lines += ["", "### Failed tests", ""]
        lines += ["- `{}` {}".format(f["module"], f["test"]) for f in failed_tests]
    if skipped_tests:
        lines += ["", "### Skipped tests", ""]
        lines += ["- `{}` {}".format(s["module"], s["test"]) for s in skipped_tests]
    with open(path, "a") as f:
        f.write("\n".join(lines) + "\n\n")


def main():
    test_path, app_name = sys.argv[1], sys.argv[2]
    module_list = sys.argv[3:]
    flagged = set(os.environ.get("FAILED_MODULES", "").split())
    keep_module_reports = os.environ.get("TEST_MODULE_REPORTS", "1") != "0"

    modules = {}
    suites = []
    all_cases = []
    failed_tests = []
    skipped_tests = []
    parsed_reports = []
    for module in module_list:
        log_dir = os.path.join(test_path, "logs", module)
        log = os.path.join(log_dir, "output.log")
        exit_code = read_exit_code(log_dir)
        merge_shard_reports(test_path, app_name, module)
        report = os.path.join(test_path, "reports", "{}_{}.xml".format(app_name, module))
        root, cases = parse_report(report)
        failed = module in flagged or exit_code != 0
        modules[module] = {
            "exit_code": exit_code,
            "status": "failed" if failed else "passed",
            "report": report if os.path.isfile(report) else None,
            "log": log,
            "tests": count(cases) if cases is not None else None,
            "cases": cases or [],
        }
        if root is not None:
            parsed_reports.append(report)
            for suite in root.iter("testsuite"):
                suite.set("name", "{}.{}".format(module, suite.get("name", "")))
                suites.append(suite)
            all_cases += cases
        failed_names = [case["name"] for case in cases or [] if case["status"] == "failed"]
        failed_tests += [{"module": module, "test": name} for name in failed_names]
        skipped_tests += [{"module": module, "test": case["name"]}
                          for case in cases or [] if case["status"] == "skipped"]
        if failed and not failed_names:
            failed_tests.append({"module": module, "test": "(module failed, see {})".format(log)})

    totals = count(all_cases)
    merged = os.path.join(test_path, "report.xml")
    if suites:
        write_merged(merged, app_name, suites, totals)
        if not keep_module_reports:
            for report in parsed_reports:
                os.remove(report)
            for info in modules.values():
                info["report"] = None
    elif os.path.isfile(merged):
        os.remove(merged)

    summary = {
        "app": app_name,
        "status": "failed" if failed_tests else "passed",
        "report": merged if suites else None,
        "tests": totals,
        "failed_tests": failed_tests,
        "skipped_tests": skipped_tests,
        "modules": {
            m: {k: v for k, v in info.items() if k != "cases"} | {
                "failed_tests": [c["name"] for c in info["cases"] if c["status"] == "failed"],
            }
            for m, info in modules.items()
        },
    }
    with open(os.path.join(test_path, "summary.json"), "w") as f:
        json.dump(summary, f, indent=4)
        f.write("\n")

    if modules:
        print_recap(modules, totals, failed_tests, skipped_tests, os.environ.get("VERBOSE", "0").casefold() not in ("", "0", "false"))
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary and modules:
        write_step_summary(step_summary, app_name, modules, totals, failed_tests, skipped_tests)


if __name__ == "__main__":
    main()
