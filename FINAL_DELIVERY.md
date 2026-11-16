# Verixa final delivery: UC1 to UC11

> **This branch is `verixa-fyp1`: FYP I only (UC1 to UC7).** The four FYP II features (QA Memory, Suggest a Fix,
> Regression Comparison and Risk Trends, UC8 to UC11) are not in this branch. They are added on top of it in the
> branch `verixa-fyp2`. Where this file mentions them, it describes `verixa-fyp2`.
>
> Tests on this branch: 505 Python tests pass; the browser suites give 157 passed and 1 skipped on purpose;
> `tests/e2e/inputs.spec.ts` checks 54 inputs.

All eleven use cases of the SRS (version 1.1) are built and tested. UC1 to UC3 were done before. This delivery adds
UC4 to UC11 on the branch `final_v7`.

## What a tester can do now

| Use case | Where on the dashboard | Main code |
|---|---|---|
| UC1 Account and Project Setup, plus the **staging address** | Integrations | `backend/api.py`, `backend/qa_api.py` (`/api/project/staging`) |
| UC2 Test Library Upload | Test Library | `backend/validators.py`, `backend/library.py` |
| UC3 Pull Request Risk Scoring (High risk listed first) | Risk Analysis | `agents/analysis.py`, `agents/risk_rules.py` |
| UC4 One Click Test Execution | Risk Analysis, **Run Now** | `backend/qa_service.py` (`start_run`, `execute_run`), `backend/execution.py` |
| UC5 Coverage Gap Test Drafting | Test Runs, "Drafted tests" | `qa_service.draft_gap_tests`, `agents/report.py` (`draft_test`, `check_draft`) |
| UC6 Results and Evidence View | Test Runs, open a result | `execution.save_evidence`, `qa_api.evidence` |
| UC7 Manual File to Jira | Test Runs or Jira Tickets | `qa_service.draft_ticket`, `qa_service.file_ticket`, `backend/jira.py` |
| UC8 QA Memory | QA Memory | `backend/memory.py` |
| UC9 Suggest a Fix | Test Runs, a real bug | `qa_service.suggest_fix`, `agents/report.py` (`suggest_fix`, `check_fix`) |
| UC10 Regression Comparison | Test Runs, "Compare runs" | `qa_service.compare` |
| UC11 Cross PR Risk Trend Reporting | Risk Trends | `qa_service.trends` |

## One run, start to end

```text
Run Now (the only way tests start, BR1)
  -> Test Agent picks specs from the risk label and changed modules (High risk = everything), plus specs that
     failed in this module before (QA Memory)
  -> staging check: a page that answers 404 means "deployment pending", never "failed" (BR4)
  -> Playwright and Newman run together on staging, in a locked down process (see Security)
  -> every result is sorted: passed, real bug, temporary error (retried once, BR5), deployment pending, skipped
  -> proof saved on disk (screenshot, trace, console log, network log), secrets removed from the logs (BR10)
  -> real bugs go to QA Memory, and to the Report Agent, which drafts one Jira ticket per bug (BR3)
  -> the Test Agent drafts a test for each changed module no test covers (BR11: unused until approved)
  -> the Manager checks every agent answer and sends it back up to AGENT_MAX_ATTEMPTS times (BR7)
Nothing reaches Jira until the tester presses "Approve and file in Jira" (BR2).
```

## Decisions taken for the open items (Appendix C)

| TBD | Decision |
|---|---|
| TBD3 retries | 3, set by `AGENT_MAX_ATTEMPTS`. The same limit for every agent |
| TBD5 still failing after the retry | A temporary error stays a temporary error. It gets no ticket |
| TBD6 approved drafted test | It is added to the Test Library and runs on the next Run Now |
| TBD7 editing the ticket | The tester can edit title, likely cause, steps and priority. Priority starts from the risk label, and the suggested assignee is the pull request's author |
| TBD8 one command run | Not built. Run Now is the only way |
| TBD13 marking a label wrong | A tester can mark a label wrong and say which label was expected. The label stays (it comes from rules); the remark is saved to QA Memory (Req 8.1) and shown with later labels of the same module |
| TBD15 memory entries | A tester can remove a wrong entry. Entries are kept until then |
| TBD16 Suggest a Fix | A button on each real bug. Nothing is written automatically |
| TBD17 trends | Periods of 7, 30, 90 or 365 days. At least 3 scored pull requests (`TREND_MIN_PULL_REQUESTS`). No export |

All limits are in `.env` (see the end of `.env.example`), and none is fixed in code.

## Security

- Every new route needs a signed-in account. A row of another account answers **404**, so ids cannot be probed. Every
  change checks the `Origin` header.
- The staging address must be http or https, without a password or a `?` part. Cloud metadata addresses
  (169.254.x.x, also written in IPv6) are always refused, and so is the Verixa server itself. Private addresses can be
  turned off with `ALLOW_PRIVATE_STAGING=false`.
- Uploaded tests may only import `@playwright/test`. `require`, `process`, `globalThis`, dynamic `import()`, `eval`,
  `new Function`, `.constructor(...)` and `file://` are refused at upload, in the browser and on the server.
- Every run gets its own folder, deleted afterwards. Its environment holds no `.env` value, token or database address
  (proven by `tests/test_qa_system.py`). It has a time limit that kills every child process. Runs are limited per hour.
- Proof is served only from inside the evidence folder, and only to its owner. Secrets are removed from logs, ticket
  text, memory entries and everything sent to a model. Text from a run is passed to models as data, never as instructions.
- A suggested fix is text only. Verixa has no code that writes to a repository.
- What goes to Jira: the ticket text has keys, tokens and passwords removed, also from what the tester typed. The
  screenshot and the cleaned logs are attached. The raw browser trace is not, because it records everything the
  browser sent. It stays downloadable in Verixa for its owner (proven by `tests/test_qa_flow.py`).

**Honest limit:** checking the text of uploaded code cannot catch every disguise. Every run is already isolated:
it has no secrets in its environment, a time limit and its own folder. On a shared or public server, also run the
app as a low privilege user or in a container.

## Tests

| Level | What | Result |
|---|---|---|
| Unit | `tests/test_qa_units.py`: staging rules, test selection, report parsing, evidence, agent checks, Manager loop, memory vectors | pass |
| Integration | `tests/test_qa_flow.py`: every new route through the real app and database, mostly negative and attack inputs | pass |
| System | `tests/test_qa_system.py`: real Playwright and Newman against a staging app with bugs on purpose | pass |
| UAT / UX | `tests/e2e/qa.spec.ts`: the whole loop in a real browser, plus another account, XSS and phone width | 14 of 14 pass |
| Inputs | `tests/e2e/inputs.spec.ts`: 68 correct, negative, edge and attack inputs across the whole app. The table of results is written to `tests/e2e/test-results/inputs.md` | 68 of 68 pass |
| Regression | every earlier Python and browser test | pass |

All Python tests together: 515. All browser projects: 162 passed and 1 skipped on purpose (it needs a real mailbox).

Without a `.venv`, set `VERIXA_PYTHON` to the Python to use (and `PYTHONPATH` to `.pydeps`) before running the browser tests.

## Setup after pulling

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend; npm install; npm run build; cd ..
cd runner; npm install; npx playwright install chromium; cd ..
```

Then add the staging address on Integrations and press Run Now on a pull request.
