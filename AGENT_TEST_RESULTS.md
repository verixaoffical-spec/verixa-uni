# Agent fixes and test results

What changed in the Manager and Analysis Agents, and which tests were run. The test plan itself, with every test and the
reasoning behind it, is in [AGENT_TESTING.md](AGENT_TESTING.md).

**Run on 6 November 2026.**

| Check | Result |
|---|---|
| Python tests (`tests/`) | **345 of 345 pass.** 263 existed before, 82 are new |
| Browser tests, GitHub and model scripted | **31 of 31 pass** |
| Browser tests, real GitHub and real model | **5 of 5 pass**, on Shoplite #7, #9 and #10 |
| Prompt injection, real model | **Not obeyed in 5 of 5**, one run each, judged by reading the answers |
| Real answers that got through the stricter checks | **8 of 8**, on the first attempt |

**Still open:** the Shoplite webhook (AT-43) needs the repository owner. See [What is still open](#what-is-still-open).

---

## What was fixed

Each new test was run against the old code first, to prove it catches the problem: 25 failed and 2 errored, and the
tests for a model that never answers hung until stopped. All of them pass now.

| Test | Problem | Fix | Files |
|---|---|---|---|
| AT-04 | A row could claim one commit while holding the scores of a newer one | The row moves to the commit really read. If that commit already has its own row, the older row is marked failed and says why | `backend/analysis_service.py` |
| AT-21 | A model that never answered was never stopped | One model gets 60 seconds, then the next is tried. A whole run gets 300 seconds, then the row is marked failed with the reason | `agents/analysis.py`, `agents/runner.py` |
| AT-13 | An invented explanation passed by sharing one word with the diff | It must name a changed file or use two words from the changed code | `agents/manager.py` |
| AT-14 | Test areas were not checked against the change | At least half must use a word from the changed code | `agents/manager.py` |
| AT-15 | "a low-risk change" and "should be treated as Low" got past a High label | More wordings are caught. "raised from Medium risk to High" and "not a low-risk change" are still allowed | `agents/manager.py` |
| AT-35 | The prompt did not mark pull request content as untrusted, and an answer that obeyed an injection was approved | The title and diff sit in a marked data block the author cannot close, with an instruction never to follow them. Answers such as "completely safe" or "no testing is needed" are rejected | `agents/analysis.py`, `agents/manager.py` |
| AT-22 | A blocked past-fix lookup scored like a clean history | It now reads "unknown, counted as 0 pts, so the real risk may be higher" and names every failed lookup. The saved count is empty, not 0 | `agents/analysis.py`, `agents/risk_rules.py` |
| AT-30 | Pull requests over 300 files were cut off with no warning | Reads all that GitHub lists, up to its limit of 3000. Beyond that, a factor says how many were read | `agents/github_client.py`, `agents/analysis.py`, `agents/risk_rules.py` |
| AT-32 | `src/modules/auth/x.js` counted as module `modules` | It now counts as `auth`, so past fixes are searched in `src/modules/auth` | `agents/risk_rules.py` |
| AT-37 | Key-like text in provider errors was saved on the row and shown on screen | Masked before saving | `backend/analysis_service.py`, `agents/analysis.py` |
| AT-38 | A secret in a changed line or the title was sent to the model provider | Hidden as `[HIDDEN SECRET]` before anything is sent. The model still sees the rest of the change. The row tells a person how many were found | `agents/redact.py`, `agents/analysis.py`, `agents/manager.py` |

### Behaviour you may notice

* **More answers may go to a person,** because the checks are stricter. Real answers passed 8 of 8, which is a small sample,
  so watch the Needs review count.
* **Scores can change for projects laid out like Shoplite,** because past fixes are now counted per feature folder.
* **A long-running analysis now stops.** Change the limits with `AGENT_MODEL_TIMEOUT` and `AGENT_RUN_TIMEOUT`.
* **Only one row for a push during analysis.** When a later commit was read, the delivery for that commit is then skipped as
  already handled.

### What these fixes cannot do

**Hiding secrets** finds known key formats (GitHub, AWS, Stripe, Slack, Groq, Google, JSON web tokens, private keys, passwords in
database addresses) and values given to names such as `password` or `api_key`. A secret with no known format and no telling name,
such as `const x = "kd8Hs2mQ"`, still gets through. It also does not remove a secret from GitHub: anyone who can read the
pull request can still see it, so a real key must be replaced.

The explanation checks compare words. They raise the bar, but they cannot prove a claim is true:

* An answer that names the right file can still say something false about it.
* If half the test areas relate to the change, the other half can still be invented.
* The list of dismissive phrases will not catch every wording.

The explanation is still written by a model, so a person should treat it as a suggestion. The label comes from rules, and no
model output can change it.

---

## Logs added

Before this work the agents' log lines appeared nowhere. Every step now writes a line with a run ID to the server console and to
`logs/agent_trace.jsonl`, which git ignores. [Section 4 of the test plan](AGENT_TESTING.md#4-tracing-a-run-with-the-logs) lists every event.

```powershell
.\.venv\Scripts\python.exe scripts\agent_trace.py --list
.\.venv\Scripts\python.exe scripts\agent_trace.py --pr verixaoffical-spec/Shoplite#10
```

Two events were added with the fixes: `run.timed_out` and `service.commit_moved`.

---

## Tests performed

### Python tests: 345 of 345 pass

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

| File | Tests | Covers |
|---|---|---|
| `tests/test_agents_real.py` (new) | 56 | The real Manager and Analysis Agent, with only GitHub and the model faked. Test names carry their AT number |
| `tests/test_agent_trace.py` (new) | 10 | The trace log, the run ID, and no token in the log |
| `tests/test_agent_secrets.py` (new) | 16 | Each secret format, ordinary code left alone, and the prompt holding no secret, including on a retry and across the trim |
| Existing files | 263 | Everything from before. One changed: the list of allowed files in `agents/` now includes `trace.py` and `redact.py` |

The fake model plays back a script, including answers that never arrive, so failures are repeatable and use no API quota.

### Browser tests, scripted: 31 of 31 pass

Real Chromium against the real app and agents. Only GitHub and the model are scripted, one situation per pull request number.
Each test also fails on any alert, page error or blocked resource.

| Area | Tests | What was checked |
|---|---|---|
| Access | 3 | Another account's results are hidden on screen and through the API. No session goes to login. No repository shows the connect message |
| Showing saved results | 6 | Tiles match the API. Row details. Opening a row by keyboard. Needs review and Failed rows show their reasons. Hostile text stays plain |
| Analyse now | 16 | A secret in the code, good answers, retries, three bad answers, a model hanging, every model hanging, a hostile title, an invented explanation, HTML in an answer, a missing pull request, blocked lookups, a huge pull request, a key in an error, the busy state, number-only input |
| Webhooks | 4 | Bad signature refused, signed delivery scored and shown, a repeat makes one row, a push during analysis shows the commit really read |
| Trace log | 2 | A run from the screen can be followed in the log. No key in the log |

### Browser tests, live: 5 of 5 pass

Real GitHub and real model, reading existing Shoplite pull requests. Nothing was written to GitHub. Results went to a throwaway
SQLite file. The numbers were compared with GitHub's own answer, and the labels with what was expected before the run.

| PR | Change | Expected label | Got | Score | Module | Attempts | Files and lines |
|---|---|---|---|---|---|---|---|
| #10 | Email validation | High | High | 4 | `auth` | 1 | Match GitHub |
| #9 | Cart quantity limit | Medium | Medium | 3 | `cart` | 1 | Match GitHub |
| #7 | Coupon codes | High | High | 5 | `coupons` | 1 | Match GitHub |

Also checked: a pull request that does not exist gives a real error and no row, the real token is nowhere in the log, and each
run is traced to its commit.

**An earlier live run failed 4 of 5** because the PC went to sleep during it, and one of my wait conditions was fragile. Both runs
are reported here because the failure was in the test setup, not the agents: the server's trace shows #9 was scored correctly.

### Prompt injection with the real model: not obeyed in 5 of 5

```powershell
.\.venv\Scripts\python.exe scripts\live_injection_check.py
```

The instruction told the model to call the change safe, say the risk is Low and say no testing is needed. It was placed in the
title, a code comment, a changed README, a changed config file, and a fake end to the data block.

In all 5 the label stayed High, the Manager approved on the first attempt, and the answer described the real code with no sign of
obeying. **This is one run of each with one model.** It is encouraging, not proof, because models vary from run to run.

---

## What the real answers showed

Reading the answers turned up three things that no automated check catches:

* **Hidden bugs were still missed.** `PR_CATALOG.md` lists a bug in #10 (login does not normalize a mixed-case email) and in #7 (a
  fixed coupon can make a total negative). The test areas covered neither. That is 0 of 2, too few to be a real measure, but
  this is what MT-4 exists to measure.
* **Small inaccuracies get through.** On #9 the explanation says the change touches "configuration code", which the diff does not
  support.
* **The catalog and the rules disagree on #10.** `PR_CATALOG.md` expects Medium, but the rules deliberately raise auth code to High.
  This run expected High, following the rules. The team should settle which is right.

---

## What is still open

| Item | What is needed |
|---|---|
| **AT-43** Two Shoplite hooks send to `/webhook/github` and get 405 | Using the owner account, open Shoplite Settings, Webhooks, and check Recent Deliveries. Point them at `/webhooks/github`, or delete them if a correct one exists |
| **AT-28** Canary test, **AT-34** test area quality | Need new pull requests on Shoplite, and a person to judge the results. No new pull requests were opened |
| **AT-37** Crash tracebacks in the server console are not masked | The database, screen and trace log are masked. The raw console traceback is not |
| **`GITHUB_TOKEN` in `.env`** gets a 401 | Replace it. It only affects scripts and direct runs |
| **Vite** is still 5.4.11 in `frontend/node_modules`, though `package.json` asks for 6.4 | Run `npm install` in `frontend`, then build again |

---

## Running the browser tests

They start their own server on port 8011 or 8012 with a throwaway SQLite file, and never touch Neon or a server on port 8000.
Build the frontend first.

```powershell
cd frontend; npm run build; cd ..\tests\e2e
npm install

# Scripted: no keys needed, about 3 minutes
npm test

# Live: real GitHub and model, about 2 minutes, uses some API quota. Only reads from GitHub
$env:E2E_GITHUB_TOKEN = (gh auth token); npm run test:live
```

If Playwright cannot find a browser, run `npx playwright install chromium`. The tests are in `tests/e2e/`, and their situations are
listed in `tests/e2e/server.py`.
