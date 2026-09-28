#!/usr/bin/env python3
"""Head-to-head bench: the /qa-browse skill's Jev fast path vs its normal
playwright-cli loop, on the same flows.

For each flow x mode x rep this launches
`claude -p --dangerously-skip-permissions --output-format json <prompt>`
and appends one JSONL row to --out. Standard library only. build_prompt() and
parse_run() are pure functions with no I/O, so tests never touch the network.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path

DEFAULT_FLOWS = Path(__file__).resolve().parent / "flows.json"
DEFAULT_OUT = Path(__file__).resolve().parent / "results.jsonl"

MODES = ("jev", "playwright")

FINISH_INSTRUCTIONS = (
    "\n\nFinish your reply with exactly these two lines:\n"
    "PATH: <jev fast path | playwright-cli fallback | both>\n"
    "VERDICT: <PASS | FAIL | STOPPED>"
)

_VERDICT_RE = re.compile(r"^VERDICT:\s*(\S+)\s*$", re.MULTILINE)
_PATH_RE = re.compile(r"^PATH:\s*(.+?)\s*$", re.MULTILINE)


def build_prompt(flow: dict, mode: str) -> str:
    """Build the `claude -p` prompt for one flow in one mode. Pure, no I/O."""
    prompt = f"/qa-browse {flow['url']} {flow['task']}"
    if mode == "playwright":
        prompt += " Do not use Jev."
    return prompt + FINISH_INSTRUCTIONS


def parse_run(stdout: str, exit_code: int, wall_s: float) -> dict:
    """Parse one `claude -p --output-format json` run. Pure, no I/O.

    Non-JSON stdout (including empty stdout from a killed/timed-out process)
    yields a row with verdict/path/cost/duration/turns all None, keeping the
    given exit_code and wall_s.
    """
    row = {
        "verdict": None,
        "path": None,
        "wall_s": wall_s,
        "cost_usd": None,
        "duration_ms": None,
        "num_turns": None,
        "exit_code": exit_code,
        "result_text": None,
    }
    try:
        data = json.loads(stdout)
    except (ValueError, TypeError):
        return row
    row["cost_usd"] = data.get("total_cost_usd")
    row["duration_ms"] = data.get("duration_ms")
    row["num_turns"] = data.get("num_turns")
    row["result_text"] = data.get("result")
    result_text = data.get("result") or ""
    verdicts = _VERDICT_RE.findall(result_text)
    paths = _PATH_RE.findall(result_text)
    if verdicts:
        row["verdict"] = verdicts[-1]
    if paths:
        row["path"] = paths[-1]
    return row


def load_flows(path: Path) -> list:
    with open(path) as fh:
        return json.load(fh)


def run_once(prompt: str, cwd: str, timeout: int, cmd: list | None = None) -> dict:
    """Run one claude session and parse its output. Impure; not unit-tested.

    cmd overrides the full command (used by tests to inject a harmless
    stand-in); default is the real `claude -p ...` invocation for prompt.
    """
    if cmd is None:
        cmd = ["claude", "-p", "--dangerously-skip-permissions", "--output-format", "json", prompt]
    start = time.monotonic()
    proc = subprocess.Popen(
        cmd, cwd=cwd, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True,
    )
    try:
        stdout, _ = proc.communicate(timeout=timeout)
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        # kill the whole process group, not just the direct child, so
        # background grandchildren (browser, playwright-cli, ...) don't
        # survive as orphans.
        os.killpg(proc.pid, signal.SIGKILL)
        stdout, _ = proc.communicate()
        exit_code = -1
    return parse_run(stdout, exit_code, time.monotonic() - start)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Head-to-head bench: /qa-browse's Jev fast path vs its playwright-cli loop.")
    p.add_argument("--flows", default=str(DEFAULT_FLOWS), help="flows.json path (default: %(default)s)")
    p.add_argument("--only", nargs="+", default=None, metavar="FLOW_ID", help="only run these flow ids")
    p.add_argument("--reps", type=int, default=1, help="repetitions per flow x mode (default: 1)")
    p.add_argument("--parallel", type=int, default=1, help="concurrent claude sessions (default: 1)")
    p.add_argument("--cwd", default=".", help="working directory to run claude in (default: current dir)")
    p.add_argument("--timeout", type=int, default=600, help="seconds allowed per session (default: 600)")
    p.add_argument("--out", default=str(DEFAULT_OUT), help="JSONL output path (default: %(default)s)")
    return p


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    flows = load_flows(Path(args.flows))
    if args.only:
        flows = [f for f in flows if f["id"] in args.only]

    jobs = [
        (flow, mode, rep)
        for flow in flows
        for mode in MODES
        for rep in range(1, args.reps + 1)
    ]

    def run_job(job):
        flow, mode, rep = job
        prompt = build_prompt(flow, mode)
        parsed = run_once(prompt, args.cwd, args.timeout)
        return {"flow": flow["id"], "mode": mode, "rep": rep, **parsed}

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "a") as fh, concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as pool:
        for row in pool.map(run_job, jobs):
            fh.write(json.dumps(row) + "\n")
            fh.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
