import json
import os
import shlex
import subprocess
from collections import defaultdict

from sbt.core import logger

_TOP_HEADERS = 15
_DROP_FLAGS = frozenset(["-c", "-MD", "-MMD"])
_DROP_WITH_VALUE = frozenset(["-o", "-MF", "-MT", "-MQ"])


def _entry_args(entry):
    args = entry.get("arguments") or shlex.split(entry["command"])
    return args[1:] if args and args[0] == "ccache" else args


def _preprocess_cmd(args):
    cmd, skip = [], False
    for arg in args:
        if skip:
            skip = False
        elif arg in _DROP_WITH_VALUE:
            skip = True
        elif arg not in _DROP_FLAGS:
            cmd.append(arg)
    return cmd + ["-E", "-P"]


def _start_preprocess(entry):
    return subprocess.Popen(
        _preprocess_cmd(_entry_args(entry)),
        cwd=entry["directory"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )


def _trace(entry):
    args = _entry_args(entry)
    if "-ftime-trace" not in args or "-o" not in args:
        return None, {}
    obj = os.path.join(entry["directory"], args[args.index("-o") + 1])
    path = os.path.splitext(obj)[0] + ".json"
    if not os.path.isfile(path):
        return None, {}
    with open(path, encoding="utf-8") as fd:
        events = json.load(fd)["traceEvents"]
    total, headers, opened = None, {}, []
    for ev in events:
        if ev.get("name") == "ExecuteCompiler":
            total = ev["dur"] / 1e6
        elif ev.get("name") == "Source" and ev.get("ph") == "b":
            opened.append(ev)
        elif ev.get("name") == "Source" and ev.get("ph") == "e" and opened:
            begin = opened.pop()
            header = begin["args"]["detail"]
            headers[header] = headers.get(header, 0.0) + (ev["ts"] - begin["ts"]) / 1e6
    return total, headers


def _measure_all(entries):
    # Threads are unusable here: the report runs from atexit, after interpreter shutdown.
    workers = os.cpu_count() or 1
    units = []
    for start in range(0, len(entries), workers):
        chunk = entries[start:start + workers]
        procs = [_start_preprocess(entry) for entry in chunk]
        for entry, proc in zip(chunk, procs):
            out, _ = proc.communicate()
            total, headers = _trace(entry)
            units.append({
                "file": entry["file"],
                "time": total,
                "lines": out.count(b"\n") if proc.returncode == 0 else None,
                "headers": headers,
            })
    return units


def print_report(compilation_db_path):
    if not os.path.isfile(compilation_db_path):
        logger.warning("compile_time: no compilation database, skipping report")
        return
    with open(compilation_db_path, encoding="utf-8") as fd:
        entries = json.load(fd)
    units = sorted(_measure_all(entries), key=lambda u: -(u["time"] or 0))

    lines = ["compile time per unit (time: clang only, lines: after preprocessing)"]
    for u in units:
        time_str = f"{u['time']:8.3f} s" if u["time"] is not None else "         -"
        lines_str = f"{u['lines']:>9}" if u["lines"] is not None else "        -"
        lines.append(f"  {time_str} {lines_str} lines  {u['file']}")

    timed = [u["time"] for u in units if u["time"] is not None]
    if timed:
        lines.append(f"total clang compile time: {sum(timed):.3f} s over {len(timed)} units")

    header_totals = defaultdict(lambda: [0.0, 0])
    for u in units:
        for header, secs in u["headers"].items():
            header_totals[header][0] += secs
            header_totals[header][1] += 1
    if header_totals:
        lines.append(f"top {_TOP_HEADERS} headers (inclusive time summed over units):")
        ranked = sorted(header_totals.items(), key=lambda kv: -kv[1][0])[:_TOP_HEADERS]
        for header, (secs, count) in ranked:
            lines.append(f"  {secs:8.3f} s {count:>5} units  {header}")

    logger.info("\n".join(lines))
