"""Render TEST_PATH/report.html from TEST_PATH/report.json (and compare.json under make bench).

Usage: report_html.py TEST_PATH
One self-contained page per run, tests or benchmarks: report.css (next to this script) is
inlined, so every sbt report page shares one look and opens offline. Dark by default, a
button switches to light (kept in localStorage); charts are inline SVG styled by the theme.
Rows carry data-kind / data-status / data-name: the toolbar filters them by name and status,
column headers sort them, and each module block counts what the filter leaves.
"""
import html
import json
import math
import os
import re
import statistics
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TIME_UNITS_NS = {"ns": 1.0, "us": 1e3, "ms": 1e6, "s": 1e9}
# Google Benchmark run fields that are not user counters
RUN_FIELDS = {
    "name", "family_index", "per_family_instance_index", "run_name", "run_type", "repetitions",
    "repetition_index", "threads", "iterations", "real_time", "cpu_time", "time_unit",
    "aggregate_name", "aggregate_unit", "error_occurred", "error_message", "skipped", "skip_message",
    "label", "items_per_second", "bytes_per_second", "big_o", "rms", "complexity_n",
}
STATUS_RANK = {"failed": 0, "skipped": 1, "passed": 2}
COMPARE_RANK = {"regression": 0, "improvement": 1, "noise": 2, "unmeasured": 3, "new": 4, "removed": 5, "same": 6}
# chart geometry (svg user units, scaled to the page width)
LABEL_W, PLOT_W, VALUE_W, ROW_H, AXIS_H = 300, 600, 110, 22, 26
# more failures than this start collapsed
OPEN_FAILURES = 10
# past this many compared benchmarks, the change chart draws the changed ones only
CHART_ALL_ROWS = 30

SCRIPT = r"""
(function () {
  var root = document.documentElement, key = "sbt-report-theme";
  var theme = document.getElementById("theme");
  function applyTheme(name) {
    root.dataset.theme = name;
    theme.textContent = name === "dark" ? "Light theme" : "Dark theme";
  }
  var saved = null;
  try { saved = localStorage.getItem(key); } catch (e) {}
  applyTheme(saved === "light" ? "light" : "dark");
  theme.addEventListener("click", function () {
    var name = root.dataset.theme === "dark" ? "light" : "dark";
    applyTheme(name);
    try { localStorage.setItem(key, name); } catch (e) {}
  });

  function each(selector, fn, scope) { Array.prototype.forEach.call((scope || document).querySelectorAll(selector), fn); }
  document.getElementById("expand").addEventListener("click", function () { each("details", function (d) { d.open = true; }); });
  document.getElementById("collapse").addEventListener("click", function () { each("details", function (d) { d.open = false; }); });

  var search = document.getElementById("search"), shown = document.getElementById("shown");
  function pressed(kind) {
    var set = {};
    each('.chips[data-kind="' + kind + '"] .chip[aria-pressed="true"]', function (c) { set[c.dataset.status] = true; });
    return Object.keys(set).length ? set : null;
  }
  function apply() {
    var query = search.value.trim().toLowerCase(), sets = {case: pressed("case"), compare: pressed("compare")};
    var filtering = !!(query || sets.case || sets.compare);
    each("[data-kind][data-name]", function (el) {
      var set = sets[el.dataset.kind];
      el.hidden = !((!query || el.dataset.name.indexOf(query) >= 0) && (!set || set[el.dataset.status]));
    });
    var visible = 0, total = 0;
    each("details.module", function (m) {
      var rows = m.querySelectorAll('tr[data-kind="case"]'), count = 0;
      each('tr[data-kind="case"]', function (r) { if (!r.hidden) count++; }, m);
      visible += count;
      total += rows.length;
      m.querySelector(".shown-module").textContent = filtering ? count + " / " + rows.length + " shown" : "";
      m.hidden = filtering && count === 0;
      if (filtering && count) m.open = true;
    });
    shown.textContent = filtering ? visible + " of " + total + " " + shown.dataset.noun + " shown"
                                  : total + " " + shown.dataset.noun;
  }
  search.addEventListener("input", apply);
  search.addEventListener("keydown", function (e) { if (e.key === "Escape") { search.value = ""; apply(); } });
  each(".chip", function (c) {
    c.addEventListener("click", function () {
      c.setAttribute("aria-pressed", c.getAttribute("aria-pressed") === "true" ? "false" : "true");
      apply();
    });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "/" && document.activeElement !== search) { e.preventDefault(); search.focus(); }
  });

  each("th[data-sort]", function (th) {
    th.addEventListener("click", function () {
      var table = th.closest("table"), body = table.tBodies[0], index = th.cellIndex;
      var dir = th.dataset.dir === "asc" ? "desc" : "asc";
      each("th", function (other) { delete other.dataset.dir; }, table);
      th.dataset.dir = dir;
      function value(row) {
        var c = row.cells[index];
        if (c.dataset.sort !== undefined) {
          var n = parseFloat(c.dataset.sort);
          return isNaN(n) ? c.dataset.sort.toLowerCase() : n;
        }
        return c.textContent.trim().toLowerCase();
      }
      var rows = Array.prototype.slice.call(body.rows);
      rows.sort(function (a, b) {
        var x = value(a), y = value(b);
        var order = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
        return dir === "asc" ? order : -order;
      });
      rows.forEach(function (r) { body.appendChild(r); });
    });
  });

  function reveal() {
    var target = location.hash && document.getElementById(location.hash.slice(1));
    for (var node = target; node; node = node.parentElement) if (node.tagName === "DETAILS") node.open = true;
  }
  window.addEventListener("hashchange", reveal);
  reveal();
  apply();
})();
"""


def esc(value):
    return html.escape(str(value), quote=True)


def pill(status, extra=""):
    return '<span class="pill {0}{1}">{0}</span>'.format(esc(status), " " + extra if extra else "")


def seconds(value):
    if value is None:
        return "-"
    if value >= 1 or value == 0:
        return "{:.2f} s".format(value)
    if value >= 1e-3:
        return "{:.1f} ms".format(value * 1e3)
    return "{:.0f} µs".format(value * 1e6)


def human_ns(value):
    if value is None:
        return "-"
    for unit, scale in (("s", 1e9), ("ms", 1e6), ("µs", 1e3)):
        if value >= scale:
            return "{:.3g} {}".format(value / scale, unit)
    return "{:.3g} ns".format(value)


def human_rate(value, unit, base=1000):
    """items_per_second as "2.67 G/s", bytes_per_second as "1.69 GiB/s"."""
    prefixes = ("G", "M", "k") if base == 1000 else ("Gi", "Mi", "Ki")
    for prefix, scale in zip(prefixes, (base ** 3, base ** 2, base)):
        if value >= scale:
            return "{:.3g} {}{}/s".format(value / scale, prefix, unit)
    return "{:.3g} {}/s".format(value, unit)


def shorten(text, limit=44):
    """Chart label: without the suffixes Google Benchmark appends, cut in the middle (arguments sit at the end)."""
    text = re.sub(r"/(iterations:\d+|real_time|process_time|manual_time)(?=/|$)", "", text)
    return text if len(text) <= limit else text[:16] + "…" + text[-(limit - 17):]


def anchor(module):
    return "mod-" + re.sub(r"[^A-Za-z0-9_-]", "-", module)


def link(base, path, label=None):
    if not path:
        return ""
    target = os.path.relpath(path, base) if os.path.isabs(path) else path
    return '<a href="{}">{}</a>'.format(esc(target), esc(label or target))


def cell(content, cls="", sort=None):
    attrs = ' class="{}"'.format(cls) if cls else ""
    if sort is not None:
        attrs += ' data-sort="{}"'.format(esc(sort))
    return "<td{}>{}</td>".format(attrs, content)


def row_attrs(kind, status, name):
    return ' data-kind="{}" data-status="{}" data-name="{}"'.format(esc(kind), esc(status), esc(name.lower()))


def table(headers, rows, numeric=(), attrs=None):
    """rows: lists of cells; attrs: one tr attribute string per row (the filterable rows)."""
    head = "".join('<th data-sort{}>{}</th>'.format(' class="num"' if i in numeric else "", esc(h))
                   for i, h in enumerate(headers))
    body = "".join("<tr{}>{}</tr>".format(attrs[i] if attrs else "", "".join(cells)) for i, cells in enumerate(rows))
    return '<div class="panel"><table><thead><tr>{}</tr></thead><tbody>{}</tbody></table></div>'.format(head, body)


def section(anchor_id, title, content, counts="", open_=True):
    return '<details class="section" id="{}"{}><summary><h2>{}</h2>{}</summary>{}</details>'.format(
        anchor_id, " open" if open_ else "", esc(title),
        '<span class="counts">{}</span>'.format(counts) if counts else "", content)


def chart(title, svg_code, legend_code="", open_=True):
    return '<details class="chart"{}><summary>{}</summary>{}{}</details>'.format(
        " open" if open_ else "", esc(title), legend_code, svg_code)


def legend(items):
    return '<div class="legend">{}</div>'.format("".join(
        '<span><i style="background:var(--{})"></i>{}</span>'.format(color, esc(label)) for color, label in items))


def svg(width, height, elements):
    return '<svg viewBox="0 0 {} {}" role="img">{}</svg>'.format(width, height, "".join(elements))


def text(x, y, content, cls="", align="start", title=""):
    tip = "<title>{}</title>".format(esc(title)) if title else ""
    return '<text x="{:.1f}" y="{:.1f}" class="{}" text-anchor="{}">{}{}</text>'.format(
        x, y, cls, align, tip, esc(content))


def rect(x, y, w, h, cls, title=""):
    tip = "<title>{}</title>".format(esc(title)) if title else ""
    return '<rect x="{:.1f}" y="{:.1f}" width="{:.1f}" height="{:.1f}" rx="2" class="{}">{}</rect>'.format(
        x, y, max(w, 0), h, cls, tip)


def line(x1, y1, x2, y2, cls):
    return '<line x1="{:.1f}" y1="{:.1f}" x2="{:.1f}" y2="{:.1f}" class="{}"/>'.format(x1, y1, x2, y2, cls)


def cards(totals, noun):
    items = [("total", noun, totals.get("total", 0)), ("passed", "passed", totals.get("passed", 0)),
             ("failed", "failed", totals.get("failed", 0)), ("skipped", "skipped", totals.get("skipped", 0)),
             ("", "time", seconds(totals.get("time", 0)))]
    return '<div class="cards">{}</div>'.format("".join(
        '<div class="card {}"><div class="label">{}</div><div class="value">{}</div></div>'.format(
            cls, esc(label), esc(value)) for cls, label, value in items))


def warnings_callout(report):
    warnings = report.get("warnings") or []
    if not warnings:
        return ""
    return '<div class="callout warn"><b>Timings may be unreliable</b><ul>{}</ul></div>'.format(
        "".join("<li>{}</li>".format(esc(w)) for w in warnings))


def interruptions(report):
    entries = [(e, "crashed") for e in report.get("crashed", [])] + [(e, "timed out") for e in report.get("timed_out", [])]
    if not entries:
        return ""
    return '<div class="callout error"><b>Interrupted binaries</b><ul>{}</ul></div>'.format("".join(
        "<li><b>{}</b> {}: {}</li>".format(esc(e["module"]), esc(what),
                                          esc(", ".join(e.get("tests") or []) or "running test unknown"))
        for e, what in entries))


def module_table(report, base, noun):
    rows = []
    for module, info in report.get("modules", {}).items():
        t = info.get("tests")
        counts = [cell(esc(t[k]), "num", t[k]) for k in ("total", "failed", "skipped")] if t else \
            [cell("no report (exit {})".format(esc(info.get("exit_code"))))] + [cell("")] * 2
        status = info.get("outcome") or info.get("status", "")
        rows.append([cell('<a href="#{}">{}</a>'.format(anchor(module), esc(module)), "name"),
                     cell(pill(status), sort=STATUS_RANK.get(status, 0))] + counts
                    + [cell(esc(seconds(t["time"])) if t else "-", "num", t["time"] if t else 0),
                       cell(link(base, info.get("log"), "output log"))])
    return table(["module", "status", noun, "failed", "skipped", "time", "log"], rows, numeric=(2, 3, 4, 5))


def module_summary(module, info, noun):
    t = info.get("tests") or {}
    counts = "{} {} · {} failed · {} skipped · {}".format(
        t.get("total", 0), noun, t.get("failed", 0), t.get("skipped", 0), seconds(t.get("time", 0)))
    return ('<summary><h3>{}</h3>{}<span class="shown-module"></span><span class="counts">{}</span>'
            '</summary>').format(esc(module), pill(info.get("outcome") or info.get("status", "")), esc(counts))


def module_block(module, info, noun, content, open_):
    failed = info.get("status") == "failed"
    return '<details class="module {}" id="{}"{}>{}<div class="body">{}</div></details>'.format(
        "failed" if failed else "passed", anchor(module), " open" if open_ or failed else "",
        module_summary(module, info, noun), content)


def results_chart(report, noun):
    """One stacked bar per module: passed / failed / skipped shares, counts at the end."""
    modules = [(m, i.get("tests")) for m, i in report.get("modules", {}).items() if i.get("tests")]
    if not modules:
        return ""
    elements = []
    for row, (module, t) in enumerate(modules):
        y = row * ROW_H + 4
        elements.append(text(LABEL_W - 10, y + 13, shorten(module), "label", "end", module))
        x = LABEL_W
        for status in ("passed", "failed", "skipped"):
            width = PLOT_W * t[status] / t["total"] if t["total"] else 0
            if width:
                elements.append(rect(x, y + 2, width, ROW_H - 8, "seg-" + status,
                                     "{}: {} {}".format(module, t[status], status)))
            x += width
        elements.append(text(LABEL_W + PLOT_W + 10, y + 13, "{} {}".format(t["total"], noun), "muted"))
    return chart("Results by module", svg(LABEL_W + PLOT_W + VALUE_W, len(modules) * ROW_H + 8, elements),
                 legend([("passed", "passed"), ("failed", "failed"), ("skipped", "skipped")]))


def chips(kind, counts, statuses):
    return '<div class="chips" data-kind="{}">{}</div>'.format(kind, "".join(
        '<button type="button" class="chip {0}" data-status="{0}" aria-pressed="false">{0} <b>{1}</b></button>'.format(
            status, counts.get(status, 0)) for status in statuses if counts.get(status)))


def toolbar(report, compare, noun):
    groups = chips("case", report.get("tests") or {}, ("failed", "skipped", "passed"))
    if compare:
        groups += '<span class="sep">compare</span>' + chips("compare", compare.get("counts", {}), COMPARE_RANK)
    return ('<div class="toolbar"><input id="search" type="search" placeholder="Filter by name or module  ( / )"'
            ' autocomplete="off" spellcheck="false">{}<span id="shown" class="shown" data-noun="{}"></span>'
            '<span class="spacer"></span><button id="expand" type="button">Expand all</button>'
            '<button id="collapse" type="button">Collapse all</button></div>').format(groups, noun)


def files_section(base, extra):
    files = ["report.html", "summary.json", "report.json", "report.xml"] + extra + ["reports/", "logs/"]
    items = "".join("<li>{}</li>".format(link(base, f)) for f in files
                    if f == "report.html" or os.path.exists(os.path.join(base, f)))
    return section("files", "Files", '<ul class="files">{}</ul>'.format(items))


def test_failures(report, base):
    failures = []
    for module, info in report.get("modules", {}).items():
        for case in info.get("cases", []):
            if case["status"] == "failed":
                failures.append((module, info, case["name"], case.get("message", "")))
        if info.get("status") == "failed" and not any(c["status"] == "failed" for c in info.get("cases", [])):
            failures.append((module, info, module, info.get("interruption") or "module failed"))
    if not failures:
        return ""
    blocks = ['<details class="failure"{}{}><summary><b>{}</b><span class="sub">{}</span><span class="sub">{}</span>'
              '</summary>{}{}</details>'.format(
                  row_attrs("case", "failed", "{} {}".format(name, module)),
                  " open" if len(failures) <= OPEN_FAILURES else "", esc(name), esc(module),
                  esc(message.splitlines()[0] if message else ""), "<pre>{}</pre>".format(esc(message)) if message else "",
                  link(base, info.get("log"), "output log")) for module, info, name, message in failures]
    return section("failures", "Failures", "".join(blocks), "{} failed".format(len(failures)))


def slowest(report):
    entries = report.get("slowest") or []
    if not entries:
        return ""
    rows = [[cell(esc(seconds(s["time"])), "num", s["time"]), cell(esc(s["module"])), cell(esc(s["test"]), "name")]
            for s in entries]
    return section("slowest", "Slowest tests", table(["time", "module", "test"], rows, numeric=(0,)))


def test_modules(report):
    blocks = []
    modules = report.get("modules", {})
    for module, info in modules.items():
        cases = sorted(info.get("cases", []), key=lambda c: STATUS_RANK.get(c["status"], 3))
        rows = [[cell(pill(c["status"]), sort=STATUS_RANK.get(c["status"], 3)),
                 cell(esc(c["name"]) + ('<span class="sub">{}</span>'.format(esc(c["message"]))
                                        if c.get("message") and c["status"] != "failed" else ""), "name"),
                 cell(esc(seconds(c["time"])), "num", c["time"])] for c in cases]
        attrs = [row_attrs("case", c["status"], "{} {}".format(c["name"], module)) for c in cases]
        blocks.append(module_block(module, info, "tests", table(["status", "test", "time"], rows, (2,), attrs),
                                   len(modules) == 1))
    return section("by-module", "Tests by module", "".join(blocks))


def ns(run, field):
    return run.get(field, 0) * TIME_UNITS_NS.get(run.get("time_unit", "ns"), 1.0)


def bench_groups(runs):
    groups = {}
    for run in runs:
        group = groups.setdefault(run.get("run_name") or run.get("name", ""), {"iterations": [], "aggregates": {}})
        if run.get("run_type") == "aggregate":
            group["aggregates"][run.get("aggregate_name")] = run
        else:
            group["iterations"].append(run)
    return groups


def bench_row(name, group):
    runs = group["iterations"]
    measured = [r for r in runs if not r.get("error_occurred") and not r.get("skipped")]
    real = [ns(r, "real_time") for r in measured]
    row = {
        "name": name,
        "status": "failed" if any(r.get("error_occurred") for r in runs) else ("skipped" if not measured else "passed"),
        "message": next((r.get("error_message") or r.get("skip_message") for r in runs
                         if r.get("error_message") or r.get("skip_message")), ""),
        "label": next((r["label"] for r in runs if r.get("label")), ""),
        "real": statistics.median(real) if real else None,
        "reps": real,
        "cpu": statistics.median([ns(r, "cpu_time") for r in measured]) if measured else None,
        "iterations": measured[0].get("iterations") if measured else None,
        "repetitions": len(runs),
        "cv": statistics.stdev(real) / statistics.fmean(real) if len(real) > 1 and statistics.fmean(real) else None,
        "rates": [], "counters": [],
    }
    for field, unit, base in (("items_per_second", "", 1000), ("bytes_per_second", "B", 1024)):
        values = [r[field] for r in measured if field in r]
        if values:
            row["rates"].append(human_rate(statistics.median(values), unit, base))
    for key in sorted({k for r in measured for k, v in r.items() if k not in RUN_FIELDS and isinstance(v, (int, float))}):
        row["counters"].append("{}={:.4g}".format(key, statistics.median([r[key] for r in measured if key in r])))
    return row


def decades(lo, hi):
    first, last = math.floor(math.log10(lo)), math.ceil(math.log10(hi))
    return [10 ** e for e in range(first, max(last, first + 1) + 1)]


def time_chart(rows):
    """Median real time per benchmark on a log axis, one dot per repetition."""
    values = [v for r in rows for v in r["reps"]]
    if not values:
        return ""
    ticks = decades(min(values), max(values))
    lo, hi = math.log10(ticks[0]), math.log10(ticks[-1])

    def x(value):
        return LABEL_W + PLOT_W * (math.log10(value) - lo) / (hi - lo)

    height = len(rows) * ROW_H + AXIS_H
    elements = []
    for tick in ticks:
        elements.append(line(x(tick), 0, x(tick), height - AXIS_H + 4, "grid"))
        elements.append(text(x(tick), height - 6, human_ns(tick), "tick", "middle"))
    for i, r in enumerate(rows):
        y = i * ROW_H
        elements.append(text(LABEL_W - 10, y + 15, shorten(r["name"]), "label", "end", r["name"]))
        if r["real"] is None:
            elements.append(text(LABEL_W + 6, y + 15, r["status"], "muted"))
            continue
        elements.append(rect(LABEL_W, y + 5, x(r["real"]) - LABEL_W, ROW_H - 10, "bar-" + r["status"],
                             "{}: median {}".format(r["name"], human_ns(r["real"]))))
        if len(r["reps"]) > 1:
            elements += ['<circle cx="{:.1f}" cy="{:.1f}" r="2.4" class="rep"><title>{}</title></circle>'.format(
                x(v), y + ROW_H / 2, esc(human_ns(v))) for v in r["reps"]]
        elements.append(text(LABEL_W + PLOT_W + 10, y + 15, human_ns(r["real"])))
    # a long chart starts folded: the table under it stays at hand
    return chart("Median real time (log scale), {} benchmarks".format(len(rows)),
                 svg(LABEL_W + PLOT_W + VALUE_W, height, elements),
                 legend([("accent", "median"), ("text", "repetitions")]) if any(len(r["reps"]) > 1 for r in rows) else "",
                 open_=len(rows) <= CHART_ALL_ROWS)


def sparkline(values, median):
    """Real time of each repetition in run order, the median dashed: drift, warmup or an outlier show up."""
    if len(values) < 2:
        return ""
    width, height, pad = 120, 28, 3
    lo, hi = min(values), max(values)
    span = hi - lo or 1

    def y(value):
        return height - pad - (height - 2 * pad) * (value - lo) / span

    step = (width - 2 * pad) / (len(values) - 1)
    points = " ".join("{:.1f},{:.1f}".format(pad + i * step, y(v)) for i, v in enumerate(values))
    dots = "".join('<circle cx="{:.1f}" cy="{:.1f}" r="1.8"><title>#{} {}</title></circle>'.format(
        pad + i * step, y(v), i, esc(human_ns(v))) for i, v in enumerate(values))
    return ('<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}"><line x1="0" x2="{w}" y1="{m:.1f}" '
            'y2="{m:.1f}" class="median"/><polyline points="{p}"/>{d}</svg>'
            '<span class="sub">{lo} … {hi}</span>').format(
        w=width, h=height, m=y(median), p=points, d=dots, lo=esc(human_ns(lo)), hi=esc(human_ns(hi)))


def bench_table(module, rows):
    slowest_ns = max((r["real"] for r in rows if r["real"]), default=0)
    with_reps = any(r["repetitions"] > 1 for r in rows)
    cells, attrs = [], []
    for r in rows:
        name = esc(r["name"])
        for sub in (r["label"], r["message"]):
            if sub:
                name += '<span class="sub">{}</span>'.format(esc(sub))
        spread = ""
        if r["repetitions"] > 1 and r["real"] is not None:
            spread = '<span class="sub">median of {}{}</span>'.format(
                r["repetitions"], ", cv {:.1%}".format(r["cv"]) if r["cv"] is not None else "")
        width = max(100 * r["real"] / slowest_ns, 1) if r["real"] and slowest_ns else 0
        row = [
            cell(name, "name"),
            cell('{}{}<div class="bar"><span style="width:{:.1f}%"></span></div>'.format(
                esc(human_ns(r["real"])), spread, width), "num", r["real"] if r["real"] is not None else -1),
            cell(esc(human_ns(r["cpu"])), "num", r["cpu"] if r["cpu"] is not None else -1),
            cell(esc("{:,}".format(r["iterations"]) if r["iterations"] is not None else "-"), "num",
                 r["iterations"] if r["iterations"] is not None else -1),
            cell(esc(" · ".join(r["rates"]) or "-"), "num"),
            cell("<br>".join(esc(c) for c in r["counters"]) or "-", "name"),
        ]
        if with_reps:
            row.append(cell(sparkline(r["reps"], r["real"]) or "-", sort=r["cv"] if r["cv"] is not None else -1))
        row.append(cell(pill(r["status"]), sort=STATUS_RANK.get(r["status"], 3)))
        cells.append(row)
        attrs.append(row_attrs("case", r["status"], "{} {}".format(r["name"], module)))
    headers = ["benchmark", "real time", "cpu time", "iterations", "rate", "counters"] \
        + (["repetitions"] if with_reps else []) + ["status"]
    return table(headers, cells, numeric=(1, 2, 3, 4), attrs=attrs)


def bench_modules(report):
    blocks = []
    modules = report.get("modules", {})
    for module, info in modules.items():
        rows = [bench_row(name, group) for name, group in bench_groups(info.get("benchmarks", [])).items()]
        blocks.append(module_block(module, info, "benchmarks", time_chart(rows) + bench_table(module, rows),
                                   len(modules) <= 3))
    return section("by-module", "Benchmarks by module", "".join(blocks))


def delta_chart(rows, threshold):
    """Change vs the baseline per benchmark, regressions right in red, the threshold band shaded."""
    rows = sorted((r for r in rows if r.get("delta") is not None), key=lambda r: -r["delta"])
    if not rows:
        return ""
    title = "Change vs baseline (median real time)"
    if len(rows) > CHART_ALL_ROWS:
        changed = [r for r in rows if r["status"] != "same"]
        if len(changed) < len(rows):
            title += ", {} unchanged not drawn".format(len(rows) - len(changed))
        rows = changed
        if not rows:
            return ""
    limit = max(max(abs(r["delta"]) for r in rows) * 1.1, threshold * 2, 0.01)
    center = LABEL_W + PLOT_W / 2

    def x(delta):
        return center + PLOT_W / 2 * max(min(delta / limit, 1), -1)

    height = len(rows) * ROW_H + AXIS_H
    elements = [rect(x(-threshold), 0, x(threshold) - x(-threshold), height - AXIS_H, "band",
                     "within the {:.0%} threshold".format(threshold))]
    for tick in (-limit, -limit / 2, 0, limit / 2, limit):
        elements.append(line(x(tick), 0, x(tick), height - AXIS_H + 4, "axis" if tick == 0 else "grid"))
        elements.append(text(x(tick), height - 6, "{:+.0%}".format(tick) if tick else "0", "tick", "middle"))
    several = len({r["module"] for r in rows}) > 1
    for i, r in enumerate(rows):
        y = i * ROW_H
        name = "{} {}".format(r["module"], r["benchmark"])
        label = shorten(r["benchmark"])
        elements.append(text(LABEL_W - 10, y + 15, "{} {}".format(r["module"], label) if several else label,
                             "label", "end", name))
        start, end = sorted((center, x(r["delta"])))
        elements.append(rect(start, y + 5, end - start, ROW_H - 10, "bar-" + r["status"],
                             "{}: {:+.1%} ({})".format(name, r["delta"], r["status"])))
        elements.append(text(LABEL_W + PLOT_W + 10, y + 15, "{:+.1%}".format(r["delta"]),
                             "" if r["status"] in ("regression", "improvement") else "muted"))
    return chart(title, svg(LABEL_W + PLOT_W + VALUE_W, height, elements),
                 legend([("failed", "regression"), ("passed", "improvement"), ("skipped", "noise"),
                         ("accent", "same"), ("neutral-soft", "threshold")]))


def compare_section(compare, base):
    if not compare:
        return ""
    rows = sorted(compare.get("benchmarks", []), key=lambda r: COMPARE_RANK.get(r["status"], 9))
    counts = " ".join("{} {}".format(pill(status), n) for status, n in compare.get("counts", {}).items() if n)
    mismatch = ""
    if compare.get("context_mismatch"):
        mismatch = '<div class="callout warn"><b>Context differs from the baseline</b><ul>{}</ul></div>'.format(
            "".join("<li>{}</li>".format(esc(m)) for m in compare["context_mismatch"]))

    def number(value):
        return value if value is not None else ""

    cells = [[cell(esc(r["module"]), "name"), cell(esc(r["benchmark"]), "name"),
              cell(esc(human_ns(r.get("baseline_ns"))), "num", number(r.get("baseline_ns"))),
              cell(esc(human_ns(r.get("current_ns"))), "num", number(r.get("current_ns"))),
              cell(esc("{:+.1%}".format(r["delta"]) if r.get("delta") is not None else "-"), "num", number(r.get("delta"))),
              cell(esc("{:+.1%}".format(r["cpu_delta"]) if r.get("cpu_delta") is not None else "-"), "num",
                   number(r.get("cpu_delta"))),
              cell(pill(r["status"]), sort=COMPARE_RANK.get(r["status"], 9))] for r in rows]
    attrs = [row_attrs("compare", r["status"], "{} {}".format(r["benchmark"], r["module"])) for r in rows]
    threshold = (compare.get("threshold_percent") or 0) / 100
    head = '<p class="meta"><span>baseline <b>{}</b></span><span>threshold <b>{}%</b></span></p>'.format(
        link(base, compare.get("baseline")), esc(compare.get("threshold_percent")))
    return section("compare", "Compared with the baseline", head + mismatch + delta_chart(rows, threshold) + table(
        ["module", "benchmark", "baseline", "current", "change", "cpu change", "status"], cells,
        numeric=(2, 3, 4, 5), attrs=attrs), counts)


def machine(report):
    context = next((info.get("context") for info in report.get("modules", {}).values() if info.get("context")), None)
    if not context:
        return ""
    # num_sharing is how many cpus share one cache: the count is cpus / sharing
    caches = ", ".join("L{} {} {} KiB ×{}".format(
        c.get("level"), c.get("type"), c.get("size", 0) // 1024,
        max(context.get("num_cpus", 1) // max(c.get("num_sharing", 1), 1), 1)) for c in context.get("caches", []))
    facts = [
        ("cpus", "{} × {} MHz".format(context.get("num_cpus", "?"), context.get("mhz_per_cpu", "?"))),
        ("caches", caches or "-"),
        ("load average", " ".join("{:.2f}".format(v) for v in context.get("load_avg", [])) or "-"),
        ("cpu scaling", "enabled" if context.get("cpu_scaling_enabled") else "disabled"),
        ("aslr", "enabled" if context.get("aslr_enabled") else "disabled"),
        ("library", "{} ({})".format(context.get("library_version", "?"), context.get("library_build_type", "?"))),
        ("git", context.get("git_rev") or "-"),
    ]
    items = "".join("<dt>{}</dt><dd>{}</dd>".format(esc(k), esc(v)) for k, v in facts)
    return section("machine", "Machine", '<div class="panel"><dl class="kv">{}</dl></div>'.format(items), open_=False)


def meta(report):
    build = report.get("build", {})
    context = next((info.get("context") for info in report.get("modules", {}).values() if info.get("context")), {})
    facts = [("date", report.get("date")), ("mode", build.get("mode")), ("compiler", build.get("compiler")),
             ("triplet", build.get("triplet")), ("libs", build.get("libs_type")), ("git", context.get("git_rev"))]
    return '<p class="meta">{}</p>'.format("".join(
        "<span>{} <b>{}</b></span>".format(esc(k), esc(v)) for k, v in facts if v))


def render(report, compare, css, base):
    bench = report.get("kind") == "bench"
    noun = "benchmarks" if bench else "tests"
    overview = cards(report.get("tests") or {}, noun) + warnings_callout(report) + interruptions(report) \
        + results_chart(report, noun) + module_table(report, base, noun)
    if bench:
        sections = [section("overview", "Overview", overview), compare_section(compare, base), bench_modules(report),
                    machine(report), files_section(base, ["compare.json"] if compare else [])]
    else:
        sections = [section("overview", "Overview", overview), test_failures(report, base), slowest(report),
                    test_modules(report), files_section(base, [])]
    sections = [s for s in sections if s]
    toc = "".join('<a href="#{0}">{1}</a>'.format(anchor_id, title) for anchor_id, title in (
        ("overview", "Overview"), ("failures", "Failures"), ("compare", "Compare"), ("slowest", "Slowest"),
        ("by-module", "By module"), ("machine", "Machine"), ("files", "Files"))
        if any('id="{}"'.format(anchor_id) in s for s in sections))
    header = ('<header class="top"><div><div class="kind">{} report</div><h1>{}</h1>{}</div>'
              '<div class="actions">{}<button id="theme" type="button">Light theme</button></div></header>').format(
        "Benchmarks" if bench else "Tests", esc(report.get("app", "")), meta(report),
        pill(report.get("status", ""), "status"))
    nav = '<nav class="toc"><div class="links">{}</div>{}</nav>'.format(toc, toolbar(report, compare, noun))
    return ('<!doctype html>\n<html lang="en" data-theme="dark"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            "<title>{} {} report</title><style>{}</style></head><body><main>{}{}{}"
            "<footer>Generated by sbt</footer></main><script>{}</script></body></html>\n").format(
        esc(report.get("app", "")), noun, css, header, nav, "".join(sections), SCRIPT)


def main():
    base = os.path.abspath(sys.argv[1])
    try:
        with open(os.path.join(base, "report.json")) as f:
            report = json.load(f)
        with open(os.path.join(SCRIPT_DIR, "report.css")) as f:
            css = f.read()
    except (OSError, ValueError) as e:
        print("error: cannot render the html report: {}".format(e), file=sys.stderr)
        return 1
    compare = None
    if report.get("kind") == "bench":
        try:
            with open(os.path.join(base, "compare.json")) as f:
                compare = json.load(f)
        except (OSError, ValueError):
            compare = None
    with open(os.path.join(base, "report.html"), "w") as f:
        f.write(render(report, compare, css, base))
    return 0


if __name__ == "__main__":
    sys.exit(main())
