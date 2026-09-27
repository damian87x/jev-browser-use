"""Tests for bench/summarize.py: markdown report over head-to-head JSONL rows.

Pure function summarize(rows) -> str is exercised directly on fixture dict
rows (no file I/O, no network): medians/sums land right, nulls are excluded,
FAIL counts as a run but not a pass, there's a markdown table header, and the
report never contains a percent sign (measured values only).
"""
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "bench" / "summarize.py"
spec = importlib.util.spec_from_file_location("summarize", SCRIPT)
summarize_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summarize_mod)

summarize = summarize_mod.summarize


def row(flow, mode, rep, verdict, path, wall_s, cost_usd, duration_ms=None, num_turns=None, exit_code=0):
    return {
        "flow": flow,
        "mode": mode,
        "rep": rep,
        "verdict": verdict,
        "path": path,
        "wall_s": wall_s,
        "cost_usd": cost_usd,
        "duration_ms": duration_ms,
        "num_turns": num_turns,
        "exit_code": exit_code,
    }


class MedianAndSumTests(unittest.TestCase):
    def test_median_wall_s_and_cost_across_three_reps(self):
        rows = [
            row("login", "fast", 1, "PASS", "A", 1.0, 0.10, num_turns=3),
            row("login", "fast", 2, "PASS", "A", 2.0, 0.20, num_turns=5),
            row("login", "fast", 3, "PASS", "A", 3.0, 0.30, num_turns=7),
        ]
        out = summarize(rows)
        self.assertIn("login", out)
        self.assertIn("2.0", out)   # median wall_s
        self.assertIn("0.2000", out)  # median cost_usd, 4 decimals
        self.assertIn("5", out)  # median num_turns

    def test_total_row_sums_cost_across_all_runs_in_a_mode(self):
        rows = [
            row("login", "fast", 1, "PASS", "A", 1.0, 0.10),
            row("signup", "fast", 1, "PASS", "B", 1.0, 0.25),
        ]
        out = summarize(rows)
        self.assertIn("0.3500", out)  # summed cost_usd for total fast row


class NullCostExcludedTests(unittest.TestCase):
    def test_null_cost_excluded_from_median_and_sum(self):
        rows = [
            row("login", "fast", 1, "PASS", "A", 1.0, 0.50),
            row("login", "fast", 2, "PASS", "A", 1.0, None),
        ]
        out = summarize(rows)
        # median/sum of cost only counts the one real number: 0.50
        self.assertIn("0.5000", out)

    def test_group_with_no_numbers_shows_em_dash(self):
        rows = [
            row("login", "fast", 1, "PASS", "A", None, None),
        ]
        out = summarize(rows)
        self.assertIn("—", out)


class VerdictCountingTests(unittest.TestCase):
    def test_fail_counts_as_run_but_not_pass(self):
        rows = [
            row("login", "fast", 1, "PASS", "A", 1.0, 0.10),
            row("login", "fast", 2, "FAIL", "B", 1.0, 0.10),
        ]
        out = summarize(rows)
        lines = [l for l in out.splitlines() if "login" in l and "|" in l]
        self.assertTrue(lines, "expected a table row for the login/fast group")
        line = lines[0]
        cells = [c.strip() for c in line.split("|")]
        self.assertIn("2", cells)  # runs
        self.assertIn("1", cells)  # passes


class DistinctPathsTests(unittest.TestCase):
    def test_distinct_paths_listed(self):
        rows = [
            row("login", "fast", 1, "PASS", "A", 1.0, 0.10),
            row("login", "fast", 2, "PASS", "B", 1.0, 0.10),
            row("login", "fast", 3, "PASS", "A", 1.0, 0.10),
        ]
        out = summarize(rows)
        self.assertIn("A", out)
        self.assertIn("B", out)


class ReportShapeTests(unittest.TestCase):
    def test_has_a_markdown_table_header_row(self):
        rows = [row("login", "fast", 1, "PASS", "A", 1.0, 0.10)]
        out = summarize(rows)
        self.assertRegex(out, r"\|.*flow.*\|.*mode.*\|")
        self.assertIn("---", out)

    def test_never_contains_a_percent_sign(self):
        rows = [
            row("login", "fast", 1, "PASS", "A", 1.0, 0.10),
            row("login", "fast", 2, "FAIL", "B", 2.0, 0.20),
            row("signup", "slow", 1, "PASS", "C", None, None),
        ]
        out = summarize(rows)
        self.assertNotIn("%", out)


class TotalRowTests(unittest.TestCase):
    def test_one_total_row_per_mode(self):
        rows = [
            row("login", "fast", 1, "PASS", "A", 1.0, 0.10),
            row("signup", "fast", 1, "FAIL", "B", 3.0, 0.20),
            row("login", "slow", 1, "PASS", "C", 5.0, 0.50),
        ]
        out = summarize(rows)
        self.assertIn("Totals by mode", out)
        # only the totals-by-mode section has rows scoped strictly by mode
        totals_section = out.split("Totals by mode", 1)[1]
        fast_total_lines = [
            l for l in totals_section.splitlines() if "fast" in l and "|" in l
        ]
        slow_total_lines = [
            l for l in totals_section.splitlines() if "slow" in l and "|" in l
        ]
        self.assertTrue(fast_total_lines, "expected a total row for fast mode")
        self.assertTrue(slow_total_lines, "expected a total row for slow mode")
        # total row for fast mode: 2 runs, 1 pass
        cells = [c.strip() for c in fast_total_lines[0].split("|")]
        self.assertIn("2", cells)
        self.assertIn("1", cells)


if __name__ == "__main__":
    unittest.main()
