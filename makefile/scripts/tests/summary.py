"""Write the test-run summary and print the end-of-run recap.

Usage: summary.py TEST_PATH APP_NAME [module ...]
Env: FAILED_MODULES (modules the executor flagged: exit code or sanitizer),
TEST_TIMEOUT_SECONDS (limit the executor applied; exit 124/137 then means timeout),
TEST_START_PATTERN / TEST_END_PATTERN (profile regexes naming the test a crash cut short),
TEST_INTERRUPT_PATTERN (app regex: a line its own watchdog prints, group 1 = the test),
TEST_MODULE_REPORTS (0 drops per-module gtest xml once merged),
VERBOSE (non-zero lists passed tests in the recap too),
TEST_PERF (non-empty adds the slowest tests to the recap and summary.json),
GITHUB_STEP_SUMMARY (markdown recap appended when set).
Writes TEST_PATH/summary.json and TEST_PATH/report.xml (merged gtest xml).
"""
import glob
import json
import os
import re
import shutil
import signal
import sys
import xml.etree.ElementTree as ET

SLOWEST_COUNT = 10
# timeout(1): 124 after SIGTERM, 137 when -k had to SIGKILL
TIMEOUT_EXIT_CODES = (124, 137)
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def read_exit_code(log_dir):
    try:
        with open(os.path.join(log_dir, "exit_code")) as f:
            return int(f.read().strip())
    except (ValueError, OSError):
        return None


def signal_name(exit_code):
    if exit_code is None or exit_code <= 128:
        return None
    try:
        return signal.Signals(exit_code - 128).name
    except ValueError:
        return None


def module_outcome(exit_code, flagged, timeout):
    if exit_code == 0 and not flagged:
        return "passed"
    if timeout and exit_code in TIMEOUT_EXIT_CODES:
        return "timeout"
    # 1 is the framework reporting failed tests, 0 a sanitizer report; anything else (signal, abort, no exit) crashed
    if exit_code in (0, 1):
        return "failed"
    return "crashed"


def unfinished_tests(log):
    """Tests started in *log* and never ended, or named by the app's interrupt line: what a crash or a timeout cut short."""
    start = os.environ.get("TEST_START_PATTERN")
    end = os.environ.get("TEST_END_PATTERN")
    interrupt = os.environ.get("TEST_INTERRUPT_PATTERN")
    try:
        with open(log, errors="replace") as f:
            lines = [ANSI_ESCAPE.sub("", line) for line in f]
    except OSError:
        return []
    start_re = re.compile(start) if start else None
    end_re = re.compile(end) if end else None
    interrupt_re = re.compile(interrupt) if interrupt else None
    running = {}
    for line in lines:
        match = interrupt_re.search(line) if interrupt_re else None
        if match:
            running[match.group(1)] = True
            continue
        if not start_re or not end_re:
            continue
        match = start_re.search(line)
        if match:
            running[match.group(1)] = True
            continue
        match = end_re.search(line)
        if match:
            running.pop(match.group(1), None)
    return list(running)


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


def interruption_message(info, timeout):
    if info["outcome"] == "timeout":
        return "timed out after {}s".format(timeout)
    return "crashed: {}".format(info["signal"] or "exit {}".format(info["exit_code"]))


def interruption_suite(module, info, timeout):
    """One errored case per crashed or timed out binary, so report viewers show it."""
    message = interruption_message(info, timeout)
    suite = ET.Element("testsuite", {"name": module, "tests": "1", "failures": "0", "errors": "1"})
    names = info["unfinished_tests"] or ["(binary)"]
    case = ET.SubElement(suite, "testcase", {"classname": module, "name": names[0], "time": "0"})
    ET.SubElement(case, "error", {"message": message}).text = "{}\nlog: {}".format(message, info["log"])
    return suite


def write_merged(path, app_name, suites, totals, errors):
    root = ET.Element("testsuites", {
        "name": app_name,
        "tests": str(totals["total"]),
        "failures": str(totals["failed"]),
        "skipped": str(totals["skipped"]),
        "errors": str(errors),
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


def print_recap(modules, totals, failed_tests, skipped_tests, verbose, slowest, crashed, timed_out):
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
        interruption = "  {}{}{}".format(c.red, info["interruption"], c.reset) if info["interruption"] else ""
        if info["tests"] is None:
            print("{}{:<{}}{}  no report (exit {}){}".format(
                color, module, width, c.reset, info["exit_code"], interruption))
            continue
        t = info["tests"]
        print("{}{:<{}}{}  {:>5} tests  {:>4} skipped  {:>4} failed  {:>8.3f} s{}".format(
            color, module, width, c.reset, t["total"], t["skipped"], t["failed"], t["time"], interruption))
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
    for title, entries in (("crashed:", crashed), ("timed out:", timed_out)):
        if not entries:
            continue
        print(title)
        width = max(len(e["module"]) for e in entries)
        for e in entries:
            print("  {}{:<{}}  {}  {}{}".format(c.red, e["module"], width, modules[e["module"]]["interruption"],
                                               ", ".join(e["tests"]) or "test unknown (no start line in the log)",
                                               c.reset))
    if slowest:
        print("slowest:")
        width = max(len(s["module"]) for s in slowest)
        for s in slowest:
            print("  {:8.3f} s  {:<{}}  {}".format(s["time"], s["module"], width, s["test"]))
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
        status = info["interruption"] or info["status"]
        if t is None:
            lines.append("| {} | {} | - | - | - | - |".format(module, status))
        else:
            lines.append("| {} | {} | {} | {} | {} | {:.3f} |".format(
                module, status, t["total"], t["failed"], t["skipped"], t["time"]))
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
    timeout = int(os.environ.get("TEST_TIMEOUT_SECONDS") or 0) or None
    crashed = []
    timed_out = []

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
        outcome = module_outcome(exit_code, module in flagged, timeout)
        unfinished = unfinished_tests(log) if outcome in ("crashed", "timeout") else []
        modules[module] = {
            "exit_code": exit_code,
            "status": "failed" if failed else "passed",
            "outcome": outcome,
            "signal": signal_name(exit_code) if outcome == "crashed" else None,
            "unfinished_tests": unfinished,
            "interruption": None,
            "report": report if os.path.isfile(report) else None,
            "log": log,
            "tests": count(cases) if cases is not None else None,
            "cases": cases or [],
        }
        if outcome in ("crashed", "timeout"):
            info = modules[module]
            info["interruption"] = interruption_message(info, timeout)
            if outcome == "timeout":
                timed_out.append({"module": module, "seconds": timeout, "tests": unfinished})
            else:
                crashed.append({"module": module, "exit_code": exit_code, "signal": info["signal"],
                                "tests": unfinished})
            suites.append(interruption_suite(module, info, timeout))
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
            failed_tests.append({"module": module, "test": "({}, see {})".format(
                modules[module]["interruption"] or "module failed", log)})

    totals = count(all_cases)
    merged = os.path.join(test_path, "report.xml")
    if suites:
        write_merged(merged, app_name, suites, totals, len(crashed) + len(timed_out))
        if not keep_module_reports:
            for report in parsed_reports:
                os.remove(report)
            for info in modules.values():
                info["report"] = None
    elif os.path.isfile(merged):
        os.remove(merged)

    slowest = []
    if os.environ.get("TEST_PERF"):
        slowest = sorted(
            ({"module": m, "test": c["name"], "time": c["time"]}
             for m, info in modules.items() for c in info["cases"]),
            key=lambda t: t["time"], reverse=True)[:SLOWEST_COUNT]

    summary = {
        "app": app_name,
        "status": "failed" if failed_tests else "passed",
        "report": merged if suites else None,
        "tests": totals,
        "failed_tests": failed_tests,
        "crashed": crashed,
        "timed_out": timed_out,
        "skipped_tests": skipped_tests,
        "modules": {
            m: {k: v for k, v in info.items() if k != "cases"} | {
                "failed_tests": [c["name"] for c in info["cases"] if c["status"] == "failed"],
            }
            for m, info in modules.items()
        },
    }
    if slowest:
        summary["slowest"] = slowest
    with open(os.path.join(test_path, "summary.json"), "w") as f:
        json.dump(summary, f, indent=4)
        f.write("\n")

    if modules:
        print_recap(modules, totals, failed_tests, skipped_tests, os.environ.get("VERBOSE", "0").casefold() not in ("", "0", "false"), slowest,
                    crashed, timed_out)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary and modules:
        write_step_summary(step_summary, app_name, modules, totals, failed_tests, skipped_tests)


if __name__ == "__main__":
    main()
