#!/usr/bin/env python3
"""Summarize head-to-head benchmark JSONL rows into a markdown report.

Usage:
    python3 bench/summarize.py results.jsonl

Each line of the input file is a JSON object with (at least):
    flow, mode, rep, verdict, path, wall_s, cost_usd, duration_ms,
    num_turns, exit_code

The report has one table row per flow x mode (runs, passes, median wall_s,
median cost_usd, median num_turns, distinct paths taken) followed by one
total row per mode (all runs, passes, median wall_s, summed cost_usd).

Missing numbers (null) are left out of medians and sums; a metric with no
numbers at all in its group prints as an em dash. Only measured values are
reported: no percentages, ratios, or projections.
"""
import json
import statistics
import sys

EM_DASH = "—"


def _numbers(rows, key):
    return [r[key] for r in rows if r.get(key) is not None]


def _median(rows, key):
    values = _numbers(rows, key)
    if not values:
        return None
    return statistics.median(values)


def _sum(rows, key):
    values = _numbers(rows, key)
    if not values:
        return None
    return sum(values)


def _fmt(value, decimals):
    if value is None:
        return EM_DASH
    return f"{value:.{decimals}f}"


def _fmt_turns(value):
    if value is None:
        return EM_DASH
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"


def _distinct_paths(rows):
    seen = []
    for r in rows:
        path = r.get("path")
        if path is not None and path not in seen:
            seen.append(path)
    return ", ".join(seen) if seen else EM_DASH


def _group_by(rows, key_fn):
    """Group rows by key_fn(row), preserving first-seen key order."""
    groups = {}
    for r in rows:
        key = key_fn(r)
        groups.setdefault(key, []).append(r)
    return groups


def summarize(rows):
    """Turn a list of head-to-head JSONL row dicts into a markdown report."""
    lines = []
    lines.append("# Head-to-head benchmark summary")
    lines.append("")
    lines.append("## By flow x mode")
    lines.append("")
    lines.append("| flow | mode | runs | passes | median wall_s | median cost_usd | median num_turns | paths |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")

    by_flow_mode = _group_by(rows, lambda r: (r.get("flow"), r.get("mode")))
    for (flow, mode), group in by_flow_mode.items():
        runs = len(group)
        passes = sum(1 for r in group if r.get("verdict") == "PASS")
        median_wall = _fmt(_median(group, "wall_s"), 1)
        median_cost = _fmt(_median(group, "cost_usd"), 4)
        median_turns = _fmt_turns(_median(group, "num_turns"))
        paths = _distinct_paths(group)
        lines.append(
            f"| {flow} | {mode} | {runs} | {passes} | {median_wall} | {median_cost} | {median_turns} | {paths} |"
        )

    lines.append("")
    lines.append("## Totals by mode")
    lines.append("")
    lines.append("| mode | runs | passes | median wall_s | total cost_usd |")
    lines.append("| --- | --- | --- | --- | --- |")

    by_mode = _group_by(rows, lambda r: r.get("mode"))
    for mode, group in by_mode.items():
        runs = len(group)
        passes = sum(1 for r in group if r.get("verdict") == "PASS")
        median_wall = _fmt(_median(group, "wall_s"), 1)
        total_cost = _fmt(_sum(group, "cost_usd"), 4)
        lines.append(f"| {mode} | {runs} | {passes} | {median_wall} | {total_cost} |")

    return "\n".join(lines) + "\n"


def main(argv):
    if len(argv) != 2:
        print("usage: python3 bench/summarize.py results.jsonl", file=sys.stderr)
        return 2
    rows = []
    with open(argv[1], "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    print(summarize(rows), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
