# jev-browser-use

**Fast browser QA from Claude Code or pi.** You write the goal, the text to type and what counts as a pass. [TypeSafe Jev](https://docs.typesafe.ai) picks every click through [Jev Ultrafast](https://github.com/browser-use/jev-ultrafast). The runner checks the final page itself, because the agent saying `DONE` proves nothing.

```bash
python3 skills/jev-browser-use/scripts/jev_browser_agent.py \
  --url https://en.wikipedia.org/wiki/Main_Page \
  --goal "Use the search box to find and open the article about the Rosetta Stone." \
  --allow-hosts wikipedia.org --expect 'Rosetta Stone' \
  --text "Search Wikipedia=Rosetta Stone" --json
```

```text
typesafe: present(len=107) model=jev-latest
text helper: (absent) model=google/gemini-2.5-flash base=https://openrouter.ai/api/v1
  browser: our own Chrome (pid=906154, port=36173, throwaway profile) — closed on exit
  tick  1     867 ms  actions=0  status=ready  last=-
  tick  2    1303 ms  actions=0  status=ready  last=-
  tick  3    1780 ms  actions=1  status=ready  last=fill
  tick  4    2666 ms  actions=2  status=ready  last=click
  tick  5    3433 ms  actions=2  status=ready  last=click
  tick  6    3953 ms  actions=2  status=done  last=click
  final_url: https://en.wikipedia.org/wiki/Rosetta_Stone
  independent check for 'Rosetta Stone': PASS
```

That run is real (2026-09-23, `jev-latest`). The key came from `.env`, and no text model was involved.

## What it gives you

- **Jev picks, you type.** Jev chooses which field to type into. `--text 'LABEL=VALUE'` (repeatable) supplies the value: an exact label match first, otherwise the one label contained in the field's label, ignoring case. No text model is called, and the value never leaves your machine.
- **It stops instead of guessing.** If Jev picks a field you didn't name, the run stops before typing and reports `"needs_text": "<field label>"`. Re-run with that label.
- **Its own browser.** It launches a headless Chrome on a throwaway profile and closes it on exit. Your everyday browser is never attached to.
- **Guard rails.** `--allow-hosts` aborts the run the moment the page leaves the allowlist. `--max-ticks` caps the number of Jev calls.
- **An independent pass.** `--expect` must appear in the live title, `<h1>` or URL. For forms, `--expect-field 'LABEL=VALUE'` reads the live field values instead. Exit codes: 0 pass, 4 not verified, 5 left the allowlist, 2 refused to start.
- **Waits for real pages.** It waits for the page to stop changing before the first decision, and for a scroll to actually land before Jev looks again. Without this, a GoDaddy-built site failed 5 of 5 runs; with it, 3 of 3 passed.

## Install

**Claude Code**

```text
/plugin marketplace add damian87x/jev-browser-use
/plugin install jev-browser-use@jev-browser-use
```

For a single session: `claude --plugin-dir /path/to/jev-browser-use`. The skill is `/jev-browser-use:jev-browser-use`.

**pi**

```bash
pi install git:github.com/damian87x/jev-browser-use      # user-wide
pi install -l git:github.com/damian87x/jev-browser-use   # this project only
```

Headless `pi -p` with a project-local (`-l`) install needs `-a` to trust the project's files. Without it, pi waits silently on the trust prompt.

**Once per machine, for both**

```bash
git clone https://github.com/browser-use/jev-ultrafast ~/jev-ultrafast
(cd ~/jev-ultrafast && uv sync)          # or set JEV_ULTRAFAST_REPO to another checkout
```

You also need Chrome or Chromium; set `BH_CHROME_PATH` if it isn't found on its own.

**The Jev key** ([console](https://console.typesafe.ai/settings/keys)), first match wins:

1. `TYPESAFE_API_KEY` in the environment
2. `TYPESAFE_API_KEY=` in the nearest `.env` at or above the working directory (keep it gitignored)
3. `~/.pi/agent/secrets/typesafe_api_key`
4. macOS Keychain, service `Hermes TypeSafe API`

A text-model key (`TEXT_MODEL_API_KEY`, or `OPENROUTER_API_KEY`) is optional. It's used only for fields you didn't name with `--text`.

## Measured on a real site (2026-09-24)

This is the contact form on [autonoxis.com](https://autonoxis.com), a GoDaddy-built site with a cookie banner that blocks scrolling. Jev accepted the banner, scrolled, filled Name, Email and Message, then chose DONE: 5 actions in 6–8 decision ticks (`jev-1.13.0`, ~220–660 ms per call), 3 of 3 runs, all confirmed by `--expect-field`. It never pressed Send. With one expected value deliberately wrong, the same run failed with exit 4. With an invalid key, TypeSafe returned 401 and zero actions ran.

## Limits

These come from Jev Ultrafast's DOM reader: no shadow roots, iframes, canvas, file uploads or pop-up tabs. A canvas game won't work; use Playwright for that. Don't point it at pages that show passwords, payment details or customer records.

## Development

```bash
python3 -m unittest discover -s tests    # offline; no browser, no paid calls
```

## Credits

Derived from the `jev-browser-use` skill in [hermes-jev-skills](https://github.com/kerpopule/hermes-jev-skills) by Steve Darlow (MIT). Jev Ultrafast is by [Browser Use](https://github.com/browser-use/jev-ultrafast) (MIT) and is not bundled. See [NOTICE](NOTICE).
