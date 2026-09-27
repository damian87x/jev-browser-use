"""Tests for the head-to-head bench harness (bench/head_to_head.py).

Offline only: never calls `claude` or the network. Uses fixture strings that
mimic `claude -p --output-format json` output.
"""
import importlib.util
import json
import os
import signal
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bench" / "head_to_head.py"
spec = importlib.util.spec_from_file_location("head_to_head", SCRIPT)
h2h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h2h)


def claude_json(result_text, cost=0.123, duration_ms=4567, num_turns=8):
    return json.dumps({
        "result": result_text,
        "total_cost_usd": cost,
        "duration_ms": duration_ms,
        "num_turns": num_turns,
    })


FLOW = {
    "id": "wiki-search",
    "url": "https://en.wikipedia.org/wiki/Main_Page",
    "task": "use the search box to find and open the Rosetta Stone article; pass when that article is open.",
}


class BuildPromptTests(unittest.TestCase):
    def test_jev_mode_has_no_playwright_instruction(self):
        prompt = h2h.build_prompt(FLOW, "jev")
        self.assertIn("/qa-browse", prompt)
        self.assertIn(FLOW["url"], prompt)
        self.assertIn(FLOW["task"], prompt)
        self.assertNotIn("Do not use Jev.", prompt)

    def test_playwright_mode_adds_the_instruction(self):
        prompt = h2h.build_prompt(FLOW, "playwright")
        self.assertIn("Do not use Jev.", prompt)

    def test_both_modes_ask_for_path_and_verdict_lines(self):
        for mode in ("jev", "playwright"):
            prompt = h2h.build_prompt(FLOW, mode)
            self.assertIn("PATH:", prompt)
            self.assertIn("VERDICT:", prompt)


class ParseRunTests(unittest.TestCase):
    def test_extracts_verdict_and_path_from_result_text(self):
        stdout = claude_json("some narration\nPATH: jev fast path\nVERDICT: PASS\n")
        row = h2h.parse_run(stdout, 0, 12.5)
        self.assertEqual(row["verdict"], "PASS")
        self.assertEqual(row["path"], "jev fast path")

    def test_extracts_cost_duration_and_turns_from_claude_json(self):
        stdout = claude_json("PATH: both\nVERDICT: FAIL\n", cost=0.42, duration_ms=9999, num_turns=15)
        row = h2h.parse_run(stdout, 0, 3.0)
        self.assertEqual(row["cost_usd"], 0.42)
        self.assertEqual(row["duration_ms"], 9999)
        self.assertEqual(row["num_turns"], 15)

    def test_last_occurrence_wins(self):
        text = (
            "PATH: jev fast path\nVERDICT: FAIL\nretrying...\n"
            "PATH: playwright-cli fallback\nVERDICT: PASS\n"
        )
        row = h2h.parse_run(claude_json(text), 0, 1.0)
        self.assertEqual(row["verdict"], "PASS")
        self.assertEqual(row["path"], "playwright-cli fallback")

    def test_missing_verdict_gives_none(self):
        stdout = claude_json("no verdict lines here\nPATH: jev fast path\n")
        row = h2h.parse_run(stdout, 0, 1.0)
        self.assertIsNone(row["verdict"])
        self.assertEqual(row["path"], "jev fast path")

    def test_non_json_output_keeps_exit_code_and_none_verdict(self):
        row = h2h.parse_run("not json at all", 1, 2.0)
        self.assertIsNone(row["verdict"])
        self.assertEqual(row["exit_code"], 1)

    def test_timeout_keeps_exit_code_and_none_verdict(self):
        row = h2h.parse_run("", -1, 600.0)
        self.assertIsNone(row["verdict"])
        self.assertEqual(row["exit_code"], -1)
        self.assertEqual(row["wall_s"], 600.0)

    def test_non_utf8_output_does_not_raise(self):
        # A ValueError (UnicodeDecodeError) that isn't a JSONDecodeError, e.g.
        # from truncated multi-byte output. Must not abort pool.map.
        row = h2h.parse_run(b'{"result": "\xff"}', 0, 1.0)
        self.assertIsNone(row["verdict"])
        self.assertEqual(row["exit_code"], 0)

    def test_truncated_json_does_not_raise(self):
        row = h2h.parse_run('{"result": "PATH: jev fast path\nVERDICT: PA', 1, 1.0)
        self.assertIsNone(row["verdict"])
        self.assertEqual(row["exit_code"], 1)


class RunOnceProcessGroupTests(unittest.TestCase):
    """run_once must kill the whole process group on timeout, not just the
    direct child, so background grandchildren don't survive. Uses a harmless
    stand-in command injected via run_once's cmd argument -- never calls
    claude or touches the network."""

    def test_timeout_kills_backgrounded_grandchild(self):
        fd, pid_path = tempfile.mkstemp(prefix="h2h-pid-")
        os.close(fd)
        os.unlink(pid_path)
        survivor_pid = None
        try:
            cmd = ["sh", "-c", f"sleep 30 & echo $! > {pid_path}; sleep 30"]
            row = h2h.run_once("unused-prompt", ".", 1, cmd=cmd)
            self.assertEqual(row["exit_code"], -1)

            deadline = time.monotonic() + 2.0
            pid_text = ""
            while time.monotonic() < deadline and not pid_text:
                if os.path.exists(pid_path):
                    pid_text = Path(pid_path).read_text().strip()
                if not pid_text:
                    time.sleep(0.05)
            self.assertTrue(pid_text, "background child never wrote its pid")
            survivor_pid = int(pid_text)

            alive = True
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                try:
                    os.kill(survivor_pid, 0)
                except ProcessLookupError:
                    alive = False
                    break
                time.sleep(0.05)
            self.assertFalse(alive, "background child survived the timeout")
        finally:
            if os.path.exists(pid_path):
                os.unlink(pid_path)
            if survivor_pid is not None:
                try:
                    os.kill(survivor_pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass


class FlowsFileTests(unittest.TestCase):
    def test_flows_json_has_exactly_the_three_ids(self):
        flows_path = ROOT / "bench" / "flows.json"
        with open(flows_path) as fh:
            flows = json.load(fh)
        ids = {flow["id"] for flow in flows}
        self.assertEqual(ids, {"wiki-search", "wiki-link", "autonoxis-form"})
        self.assertEqual(len(flows), 3)


if __name__ == "__main__":
    unittest.main()
