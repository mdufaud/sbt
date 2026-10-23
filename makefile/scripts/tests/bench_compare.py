"""Compare a `make bench` run with a saved baseline.

Usage: bench_compare.py BENCH_PATH APP_NAME BASELINE_DIR THRESHOLD_PERCENT [module ...]
Reads BENCH_PATH/reports/<app>_<module>.json (this run) against BASELINE_DIR/<app>_<module>.json
(Google Benchmark reports), prints the comparison (changed benchmarks only unless VERBOSE),
writes BENCH_PATH/compare.json and appends a markdown table to GITHUB_STEP_SUMMARY when set.
A benchmark compares the median real time of its repetitions. It regresses or improves past
THRESHOLD_PERCENT, unless that change stays within twice its repetitions' spread (noise).
Exits 1 when BASELINE_DIR holds no report for the modules run.
"""
import json
import os
import statistics
import sys

TIME_UNITS_NS = {"ns": 1.0, "us": 1e3, "ms": 1e6, "s": 1e9}
# facts both sides need equal for the numbers to be comparable
CONTEXT_KEYS = ("sbt_mode", "sbt_compiler", "sbt_triplet", "sbt_libs_type", "num_cpus", "library_version")
CHANGED = ("regression", "improvement", "noise", "new", "removed", "unmeasured")


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def runs_by_name(report):
    """Real and cpu times (ns) of each benchmark's measured repetitions."""
    runs = {}
    for run in report.get("benchmarks", []):
        if run.get("run_type", "iteration") != "iteration":
            continue
        entry = runs.setdefault(run.get("name", ""), {"real": [], "cpu": []})
        if run.get("error_occurred") or run.get("skipped"):
            continue
        unit = TIME_UNITS_NS.get(run.get("time_unit", "ns"), 1.0)
        entry["real"].append(run.get("real_time", 0) * unit)
        entry["cpu"].append(run.get("cpu_time", 0) * unit)
    return runs


def spread(values):
    """Coefficient of variation of the repetitions, None below two."""
    if len(values) < 2:
        return None
    mean = statistics.fmean(values)
    return statistics.stdev(values) / mean if mean else None


def change(base, current):
    if not base or not current:
        return None
    reference = statistics.median(base)
    return statistics.median(current) / reference - 1 if reference else None


def compare(base, current, threshold):
    if base is None:
        return "new", None, None
    if current is None:
        return "removed", None, None
    delta = change(base["real"], current["real"])
    if delta is None:
        return "unmeasured", None, None
    noise = max((s for s in (spread(base["real"]), spread(current["real"])) if s is not None), default=None)
    if abs(delta) <= threshold:
        return "same", delta, noise
    if noise is not None and abs(delta) <= 2 * noise:
        return "noise", delta, noise
    return ("regression" if delta > 0 else "improvement"), delta, noise


def human_ns(value):
    for unit, scale in (("s", 1e9), ("ms", 1e6), ("us", 1e3)):
        if value >= scale:
            return "{:.3g} {}".format(value / scale, unit)
    return "{:.3g} ns".format(value)


def median_or_none(values):
    return statistics.median(values) if values else None


def main():
    bench_path, app_name, baseline_dir, threshold_percent = sys.argv[1:5]
    module_list = sys.argv[5:]
    threshold = float(threshold_percent) / 100
    verbose = os.environ.get("VERBOSE", "0").casefold() not in ("", "0", "false")

    rows = []
    mismatches = []
    found = False
    for module in module_list:
        name = "{}_{}.json".format(app_name, module)
        current = load(os.path.join(bench_path, "reports", name))
        base = load(os.path.join(baseline_dir, name))
        if current is None:
            continue
        found = found or base is not None
        base = base or {}
        base_ctx, current_ctx = base.get("context", {}), current.get("context", {})
        for key in CONTEXT_KEYS:
            if key in base_ctx and base_ctx.get(key) != current_ctx.get(key):
                mismatches.append("{}: {} {} in the baseline, {} now".format(
                    module, key, base_ctx.get(key), current_ctx.get(key)))
        base_runs, current_runs = runs_by_name(base), runs_by_name(current)
        for bench in list(current_runs) + [b for b in base_runs if b not in current_runs]:
            b, c = base_runs.get(bench), current_runs.get(bench)
            status, delta, noise = compare(b, c, threshold)
            rows.append({
                "module": module,
                "benchmark": bench,
                "status": status,
                "baseline_ns": median_or_none(b["real"]) if b else None,
                "current_ns": median_or_none(c["real"]) if c else None,
                "delta": delta,
                "cpu_delta": change(b["cpu"], c["cpu"]) if b and c else None,
                "noise": noise,
            })
    if not found:
        print("error: no bench baseline report for {} in {}".format(" ".join(module_list), baseline_dir),
              file=sys.stderr)
        return 1

    counts = {status: sum(1 for r in rows if r["status"] == status) for status in ("same",) + CHANGED}
    with open(os.path.join(bench_path, "compare.json"), "w") as f:
        json.dump({"baseline": baseline_dir, "threshold_percent": float(threshold_percent),
                   "counts": counts, "context_mismatch": mismatches, "benchmarks": rows}, f, indent=4)
        f.write("\n")

    color = sys.stdout.isatty()
    paint = {"regression": "\033[0;31m", "improvement": "\033[0;32m"} if color else {}
    reset = "\033[0m" if color else ""
    shown = [r for r in rows if verbose or r["status"] != "same"]
    print("")
    print("==================== BENCH COMPARE ====================")
    print("baseline: {}  threshold: {}%".format(baseline_dir, threshold_percent))
    width = max((len(r["module"]) + len(r["benchmark"]) + 1 for r in shown), default=0)
    for r in shown:
        times = "{:>10} -> {:<10}".format(
            human_ns(r["baseline_ns"]) if r["baseline_ns"] is not None else "-",
            human_ns(r["current_ns"]) if r["current_ns"] is not None else "-")
        delta = "{:+.1%}".format(r["delta"]) if r["delta"] is not None else ""
        print("  {:<{}}  {}  {:>8}  {}{}{}".format(
            r["module"] + " " + r["benchmark"], width, times, delta,
            paint.get(r["status"], ""), r["status"], reset))
    print("------------------------------------------------------")
    print(", ".join("{} {}".format(n, status) for status, n in counts.items() if n) or "no benchmark")
    for mismatch in mismatches:
        print("  context differs: " + mismatch)
    print("======================================================")

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        lines = ["## Benchmark compare: {}".format(app_name), "",
                 "Baseline `{}`, threshold {}%: ".format(baseline_dir, threshold_percent)
                 + ", ".join("{} {}".format(n, s) for s, n in counts.items() if n), ""]
        changed = [r for r in rows if r["status"] != "same"]
        if changed:
            lines += ["| Module | Benchmark | Baseline | Current | Delta | Status |", "|---|---|---|---|---|---|"]
            for r in changed:
                lines.append("| {} | {} | {} | {} | {} | {} |".format(
                    r["module"], r["benchmark"],
                    human_ns(r["baseline_ns"]) if r["baseline_ns"] is not None else "-",
                    human_ns(r["current_ns"]) if r["current_ns"] is not None else "-",
                    "{:+.1%}".format(r["delta"]) if r["delta"] is not None else "-", r["status"]))
        lines += ["- context differs: " + m for m in mismatches]
        with open(step_summary, "a") as f:
            f.write("\n".join(lines) + "\n\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
