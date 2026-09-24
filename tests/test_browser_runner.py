"""Tests for the browser runner's ownership logic.

These never launch a real browser: they pin the flags, the binary lookup, the CDP
poll and the cleanup contract, so a live run is the only thing that needs a
machine with Chrome on it.
"""
import importlib.util
import json
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "jev-browser-use" / "scripts" / "jev_browser_agent.py"
spec = importlib.util.spec_from_file_location("jev_browser_agent", SCRIPT)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class ChromeDiscoveryTests(unittest.TestCase):
    def test_env_override_wins(self):
        self.assertEqual(runner.find_chrome({"BH_CHROME_PATH": "/bin/ls"}), "/bin/ls")
        self.assertEqual(runner.find_chrome({"CHROME_PATH": "/bin/cat"}), "/bin/cat")

    def test_invalid_env_override_never_wins(self):
        # A bad override must never be used, but the function may still fall back to a
        # real browser on this machine or return None on one without any.
        resolved = runner.find_chrome({"BH_CHROME_PATH": "/does/not/exist"})
        self.assertNotEqual(resolved, "/does/not/exist")
        self.assertTrue(resolved is None or Path(resolved).exists())


class ChromeArgsTests(unittest.TestCase):
    def test_uses_a_throwaway_profile_and_our_own_port(self):
        args = runner.chrome_args(9333, "/tmp/profile-xyz")
        self.assertIn("--remote-debugging-port=9333", args)
        self.assertIn("--user-data-dir=/tmp/profile-xyz", args)
        self.assertIn("--headless=new", args)
        # never the person's real profile
        self.assertFalse(any("Application Support" in a for a in args))
        self.assertFalse(any("9333" in a and "remote-debugging" not in a for a in args))

    def test_free_port_is_usable_and_distinct(self):
        ports = {runner.free_port() for _ in range(5)}
        self.assertTrue(all(1024 < p < 65536 for p in ports))


class CdpPollTests(unittest.TestCase):
    def test_returns_the_websocket_when_the_endpoint_answers(self):
        class Response:
            def read(self):
                return json.dumps({"webSocketDebuggerUrl": "ws://127.0.0.1:1234/devtools/browser/x"}).encode()

        ws = runner.wait_for_cdp(1234, timeout=1.0, opener=lambda url: Response())
        self.assertEqual(ws, "ws://127.0.0.1:1234/devtools/browser/x")

    def test_gives_up_when_the_endpoint_never_answers(self):
        def dead(url):
            raise OSError("connection refused")

        self.assertIsNone(runner.wait_for_cdp(1234, timeout=0.6, opener=dead))

    def test_ignores_a_payload_without_a_websocket(self):
        class Response:
            def read(self):
                return b'{"Browser": "Chrome/1"}'

        self.assertIsNone(runner.wait_for_cdp(1234, timeout=0.6, opener=lambda url: Response()))


class OwnedChromeContractTests(unittest.TestCase):
    def test_stop_is_idempotent_and_clears_the_profile(self):
        owned = runner.OwnedChrome("/bin/echo")
        owned.stop()  # never started: must not raise
        owned.stop()

    def test_failed_start_reports_and_cleans_up(self):
        owned = runner.OwnedChrome("/bin/echo", startup_timeout=0.4)
        with self.assertRaises(RuntimeError):
            owned.start()
        self.assertIsNone(owned.profile_dir)  # throwaway profile removed


class LaunchOrderTests(unittest.TestCase):
    def test_browser_starts_after_the_venv_reexec(self):
        # ensure_importable may os.execv into the vendored venv; a browser launched
        # before that swap is orphaned and its atexit cleanup never runs.
        source = SCRIPT.read_text(encoding="utf-8")
        main_body = source.split("def main(", 1)[1]
        self.assertLess(main_body.index("ensure_importable(argv)"),
                        main_body.index("start_owned_browser(args)"))

    def test_stop_is_registered_for_exit_and_signals(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("atexit.register(owned.stop)", source)
        self.assertIn("signal.SIGTERM", source)


class AllowlistTests(unittest.TestCase):
    def test_subdomains_allowed_but_not_lookalikes(self):
        self.assertTrue(runner.host_allowed("https://en.wikipedia.org/wiki/X", ["wikipedia.org"]))
        self.assertFalse(runner.host_allowed("https://evil-wikipedia.org/", ["wikipedia.org"]))
        self.assertFalse(runner.host_allowed("https://example.com/", ["wikipedia.org"]))


if __name__ == "__main__":
    unittest.main()


class CredentialFallbackTests(unittest.TestCase):
    """An agent's environment carries no keys. The TypeSafe key fell back to the secret
    store; the text-model key did not. So the loop started fine and died the first time
    Jev chose to TYPE - on most sites the very first action - with "TYPE_TEXT needs
    TEXT_MODEL_API_KEY". It only ever worked from a shell where someone had exported the
    key by hand, which is how every test and every demo had been run.
    """

    def test_the_text_key_falls_back_to_the_secret_store(self):
        seen = []

        def lookup(service, account):
            seen.append(service)
            return "sk-from-the-keychain" if service == "OPENROUTER_API_KEY" else "ts-key"

        creds = runner.resolve_credentials({"USER": "someone"}, lookup=lookup)
        self.assertEqual(creds.get("TEXT_MODEL_API_KEY"), "sk-from-the-keychain")
        self.assertIn("OPENROUTER_API_KEY", seen)

    def test_an_explicit_environment_key_still_wins(self):
        creds = runner.resolve_credentials(
            {"TEXT_MODEL_API_KEY": "sk-explicit", "USER": "someone"},
            lookup=lambda service, account: "sk-from-the-keychain")
        self.assertEqual(creds["TEXT_MODEL_API_KEY"], "sk-explicit")

    def test_no_key_anywhere_is_simply_absent_not_an_error(self):
        creds = runner.resolve_credentials({"USER": "someone"}, lookup=lambda s, a: None)
        self.assertNotIn("TEXT_MODEL_API_KEY", creds)


class CallerTextTests(unittest.TestCase):
    """--text lets the calling agent supply typed values, so no text model is needed.

    Jev still chooses which field to type into; the caller only decides what text
    goes in a field whose label it named. Values never leave the machine.
    """

    def context(self, label):
        return {"goal": "g", "field": {"label": label, "role": "textbox", "value": ""}}

    def test_pairs_split_on_the_first_equals_sign(self):
        self.assertEqual(runner.parse_text_values(["Email=a=b@x.io", " Search = Gödel "]),
                         [("Email", "a=b@x.io"), ("Search", "Gödel")])

    def test_a_pair_without_a_label_is_refused(self):
        for bad in ["=value", "no-equals-sign"]:
            with self.assertRaises(ValueError):
                runner.parse_text_values([bad])

    def test_label_match_ignores_case_and_accepts_a_contained_name(self):
        fill = runner.caller_field_text([("email", "qa@test.io")])
        value, helper = fill(self.context("Email address"))
        self.assertEqual(value, "qa@test.io")
        self.assertEqual(helper["model"], "caller")
        self.assertEqual(helper["latency_ms"], 0)

    def test_an_exact_label_beats_a_contained_one(self):
        fill = runner.caller_field_text([("Name", "short"), ("Last name", "exact")])
        self.assertEqual(fill(self.context("Last name"))[0], "exact")

    def test_two_contained_matches_are_ambiguous_not_a_guess(self):
        fill = runner.caller_field_text([("name", "a"), ("last", "b")])
        with self.assertRaises(runner.MissingText) as caught:
            fill(self.context("Last name"))
        self.assertEqual(caught.exception.label, "Last name")

    def test_an_unnamed_field_stops_with_its_label(self):
        fill = runner.caller_field_text([("Email", "qa@test.io")])
        with self.assertRaises(runner.MissingText) as caught:
            fill(self.context("Search Wikipedia"))
        self.assertEqual(caught.exception.label, "Search Wikipedia")

    def test_an_unnamed_field_uses_the_fallback_model_when_there_is_one(self):
        fill = runner.caller_field_text([], fallback=lambda ctx: ("from-model", {"model": "m", "latency_ms": 5}))
        self.assertEqual(fill(self.context("Anything")), ("from-model", {"model": "m", "latency_ms": 5}))

    def test_the_flag_is_repeatable(self):
        args = runner.build_parser().parse_args(
            ["--url", "u", "--goal", "g", "--allow-hosts", "h", "--text", "A=1", "--text", "B=2"])
        self.assertEqual(args.text, ["A=1", "B=2"])


class KeyFileTests(unittest.TestCase):
    """Inside Claude Code or pi nobody exported the key, so the runner finds it itself:
    environment, then the nearest .env above the working directory, then pi's secret file."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        self.project = self.tmp / "project" / "sub" / "dir"
        self.project.mkdir(parents=True)
        (self.home / ".pi" / "agent" / "secrets").mkdir(parents=True)

    def resolve(self, env=None):
        return runner.resolve_credentials(env or {"USER": "u"}, lookup=lambda s, a: None,
                                          cwd=self.project, home=self.home)

    def test_the_nearest_dotenv_above_the_working_directory_supplies_the_key(self):
        (self.tmp / "project" / ".env").write_text('# comment\nexport TYPESAFE_API_KEY="ts-from-dotenv"\n')
        self.assertEqual(self.resolve()["TYPESAFE_API_KEY"], "ts-from-dotenv")

    def test_a_closer_dotenv_wins_and_an_empty_value_is_skipped(self):
        (self.tmp / "project" / ".env").write_text("TYPESAFE_API_KEY=ts-outer\n")
        (self.tmp / "project" / "sub" / ".env").write_text("TYPESAFE_API_KEY=\n")
        (self.project / ".env").write_text("OTHER=1\n")
        self.assertEqual(self.resolve()["TYPESAFE_API_KEY"], "ts-outer")

    def test_pi_secret_file_is_the_last_file_fallback(self):
        (self.home / ".pi" / "agent" / "secrets" / "typesafe_api_key").write_text("ts-from-pi\n")
        self.assertEqual(self.resolve()["TYPESAFE_API_KEY"], "ts-from-pi")

    def test_the_environment_still_wins_over_files(self):
        (self.tmp / "project" / ".env").write_text("TYPESAFE_API_KEY=ts-dotenv\n")
        self.assertEqual(self.resolve({"TYPESAFE_API_KEY": "ts-env"})["TYPESAFE_API_KEY"], "ts-env")

    def test_the_text_key_is_read_from_dotenv_too(self):
        (self.tmp / "project" / ".env").write_text("OPENROUTER_API_KEY=sk-or\n")
        self.assertEqual(self.resolve()["TEXT_MODEL_API_KEY"], "sk-or")

    def test_nothing_anywhere_is_absent(self):
        self.assertNotIn("TYPESAFE_API_KEY", self.resolve())


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class SettleTests(unittest.TestCase):
    """Jev must not decide on a page that is still building itself.

    Measured on a GoDaddy site: the first decision landed mid-hydration, the executor
    rejected it as stale, and the run drifted. Wait until the page stops changing.
    """

    def settle(self, values, quiet=1.0, cap=5.0):
        clock, reads = FakeClock(), iter(values)
        last = [None]

        def read():
            last[0] = next(reads, last[0])
            return last[0]
        waited = runner.wait_until_settled(read, quiet_s=quiet, cap_s=cap, clock=clock.time, sleep=clock.sleep)
        return waited, clock.now

    def test_a_stable_page_returns_after_one_quiet_window(self):
        settled, elapsed = self.settle(["a"] * 100)
        self.assertTrue(settled)
        self.assertAlmostEqual(elapsed, 1.0, delta=0.15)

    def test_a_change_restarts_the_quiet_window(self):
        settled, elapsed = self.settle(["a"] * 8 + ["b"] * 100)
        self.assertTrue(settled)
        self.assertGreater(elapsed, 1.6)

    def test_a_page_that_never_settles_gives_up_at_the_cap(self):
        settled, elapsed = self.settle([str(i) for i in range(1000)], cap=2.0)
        self.assertFalse(settled)
        self.assertAlmostEqual(elapsed, 2.0, delta=0.15)

    def test_zero_cap_does_not_wait(self):
        settled, elapsed = self.settle(["a"] * 10, cap=0)
        self.assertEqual(elapsed, 0)


class ScrollWaitTests(unittest.TestCase):
    """A wheel scroll can land ~1 s after the input call returns. Observing before it
    lands shows Jev an unmoved page, and it reasonably answers BLOCKED."""

    def wait(self, values, cap=1.5):
        clock, reads = FakeClock(), iter(values)
        last = [None]

        def read():
            last[0] = next(reads, last[0])
            return last[0]
        moved = runner.wait_for_change(read, before=0, cap_s=cap, clock=clock.time, sleep=clock.sleep)
        return moved, clock.now

    def test_returns_as_soon_as_the_position_moves(self):
        moved, elapsed = self.wait([0] * 10 + [560])
        self.assertTrue(moved)
        self.assertAlmostEqual(elapsed, 0.5, delta=0.1)

    def test_gives_up_at_the_cap_when_nothing_moves(self):
        moved, elapsed = self.wait([0] * 1000, cap=1.5)
        self.assertFalse(moved)
        self.assertAlmostEqual(elapsed, 1.5, delta=0.1)


class TimingFlagTests(unittest.TestCase):
    def test_defaults_are_on(self):
        args = runner.build_parser().parse_args(["--url", "u", "--goal", "g", "--allow-hosts", "h"])
        self.assertEqual((args.settle_max_ms, args.scroll_wait_ms), (5000, 1500))

    def test_the_run_settles_before_its_first_decision(self):
        body = SCRIPT.read_text().split("def main(", 1)[1]
        self.assertLess(body.index("wait_until_settled("), body.index("agent.run()"))
        self.assertIn("wait_for_change(", body)


class ExpectFieldTests(unittest.TestCase):
    """A filled form changes no title, heading or URL, so --expect cannot prove it.
    --expect-field reads the live field values before the tab closes."""

    OBSERVED = {"Name": "QA Test", "Email*": "qa@test.io", "Message": "hello"}

    def test_every_named_field_must_hold_its_value(self):
        ok, report = runner.fields_match(self.OBSERVED, [("Name", "QA Test"), ("email", "qa@test.io")])
        self.assertTrue(ok)
        self.assertEqual(report, {"Name": True, "email": True})

    def test_a_wrong_value_fails(self):
        ok, report = runner.fields_match(self.OBSERVED, [("Message", "bye")])
        self.assertFalse(ok)
        self.assertEqual(report, {"Message": False})

    def test_a_missing_field_fails(self):
        self.assertFalse(runner.fields_match(self.OBSERVED, [("Phone", "1")])[0])

    def test_an_ambiguous_label_fails_instead_of_guessing(self):
        self.assertFalse(runner.fields_match({"First name": "a", "Last name": "a"}, [("name", "a")])[0])

    def test_no_expected_fields_is_not_a_pass(self):
        self.assertFalse(runner.fields_match(self.OBSERVED, [])[0])

    def test_fields_alone_can_verify_a_run(self):
        self.assertTrue(runner.run_verified("t", "h", "u", expect="", fields_ok=True))
        self.assertFalse(runner.run_verified("t", "h", "u", expect="", fields_ok=None))
        self.assertFalse(runner.run_verified("title", "h", "u", expect="title", fields_ok=False))
        self.assertTrue(runner.run_verified("title", "h", "u", expect="title", fields_ok=None))

    def test_the_flag_is_repeatable(self):
        args = runner.build_parser().parse_args(["--url", "u", "--goal", "g", "--allow-hosts", "h",
                                                 "--expect-field", "A=1", "--expect-field", "B=2"])
        self.assertEqual(args.expect_field, ["A=1", "B=2"])
