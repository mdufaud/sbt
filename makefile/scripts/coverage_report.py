"""Coverage gate and CI summary helpers for run_coverage.sh.

Usage:
    coverage_report.py gate-args SBT_ENV_JSON
        gcovr --fail-under-* args from app.gcov_fail_under[_branch], one per line
    coverage_report.py step-summary SBT_ENV_JSON SUMMARY_JSON RC
        append a markdown table to $GITHUB_STEP_SUMMARY when set
"""
import json
import os
import sys

_GATES = (("fail_under", "--fail-under-line"), ("fail_under_branch", "--fail-under-branch"))


def thresholds(sbt_env_json):
    try:
        with open(sbt_env_json) as f:
            coverage = json.load(f).get("coverage") or {}
    except (OSError, ValueError):
        return {}
    return {key: coverage[key] for key, _ in _GATES if coverage.get(key) is not None}


def gate_args(sbt_env_json):
    limits = thresholds(sbt_env_json)
    for key, flag in _GATES:
        if key in limits:
            print(flag)
            print(limits[key])


def step_summary(sbt_env_json, summary_json, rc):
    out = os.environ.get("GITHUB_STEP_SUMMARY")
    if not out or not os.path.isfile(summary_json):
        return
    with open(summary_json) as f:
        s = json.load(f)
    limits = thresholds(sbt_env_json)
    rows = (
        ("lines", "line", limits.get("fail_under", "-")),
        ("branches", "branch", limits.get("fail_under_branch", "-")),
        ("functions", "function", "-"),
    )
    lines = [
        "## Coverage",
        "",
        "| Metric | Covered | Total | Percent | Fail under |",
        "|---|---|---|---|---|",
    ]
    for label, key, limit in rows:
        percent = s.get("{}_percent".format(key))
        lines.append("| {} | {} | {} | {} | {} |".format(
            label, s["{}_covered".format(key)], s["{}_total".format(key)],
            "-" if percent is None else "{}%".format(percent), limit))
    lines += ["", "**Status**: {}".format("failed" if rc != "0" else "passed")]
    with open(out, "a") as f:
        f.write("\n".join(lines) + "\n\n")


def main():
    command = sys.argv[1]
    if command == "gate-args":
        gate_args(sys.argv[2])
    elif command == "step-summary":
        step_summary(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        sys.exit("unknown command: {}".format(command))


if __name__ == "__main__":
    main()
