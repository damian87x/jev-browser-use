# Head-to-head benchmark summary

## By flow x mode

| flow | mode | runs | passes | median wall_s | median cost_usd | median num_turns | paths |
| --- | --- | --- | --- | --- | --- | --- | --- |
| wiki-search | jev | 2 | 2 | 34.6 | 0.3965 | 2 | jev fast path |
| wiki-search | playwright | 2 | 2 | 24.6 | 0.4316 | 4.5 | playwright-cli fallback |
| wiki-link | jev | 2 | 2 | 34.7 | 0.3860 | 2 | jev fast path |
| wiki-link | playwright | 2 | 2 | 53.6 | 0.5727 | 11.5 | playwright-cli fallback |
| autonoxis-form | jev | 2 | 2 | 82.6 | 0.6070 | 10 | both |
| autonoxis-form | playwright | 2 | 2 | 71.7 | 0.6092 | 10 | playwright-cli fallback |

## Totals by mode

| mode | runs | passes | median wall_s | total cost_usd |
| --- | --- | --- | --- | --- |
| jev | 6 | 6 | 35.8 | 2.7790 |
| playwright | 6 | 6 | 42.7 | 3.2271 |

## Notes (2026-09-27, local package 4504910, jev-latest, Claude Code headless)

- 12 of 12 runs passed; no timeouts, no crashes, 0 browser-harness daemons left afterwards.
- `cost_usd` is the Claude session cost reported by `claude -p`. It does not include TypeSafe Jev calls, which this harness does not measure.
- Each row is a whole `/qa-browse` agent session (reading the skill, checking the page, running the flow, reporting), not only the browser part. Two repetitions per cell: treat differences as indicative, not significant.
- `autonoxis-form` in jev mode reported path `both` in both runs: the Jev fast path did not verify, and the playwright-cli fallback finished it. The harness keeps only the parsed fields, so the reason for those two fallbacks was not captured. A separate diagnostic run of the same prompt passed on the Jev path alone (exit 0, 8 ticks, fields Name/Email/Message all true, blocked_click null, Claude cost 0.4281), with the agent-written goal naming the cookie banner and "never click the logo or any link, never Send/Submit" and `--max-ticks 20`.
- No form was submitted by design: the autonoxis task says "never submit it", and on the Jev path the runner's default `--never-click` guard refuses Send/Submit.

## Rerun with result_text (2026-09-28, local package 76edddc)

`bench/results-autonoxis-rerun.jsonl`: autonoxis-form, 2 reps per mode, now with each session's final text saved as `result_text`.

- jev rep 1: PASS via path `both`. The saved text says the Jev fast path exited 4 because Jev chose BLOCKED on its first decision (0 actions, `blocked_click` null, fields all false), and the playwright-cli fallback then filled the form. The agent guessed that naming Send/Submit in the goal may cause the stop; that is not verified.
- jev rep 2: PASS on the Jev fast path alone (cookie banner click, scroll, 3 fills; 6 ticks; nothing submitted).
- So the autonoxis fallback is intermittent: Jev sometimes gives up on the first observation of this page.
