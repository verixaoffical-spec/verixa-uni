# Verixa: an agentic AI quality engineer

Verixa sits between GitHub, Playwright, Newman and Jira. When a pull request is opened it rates how risky the
change is. When the tester presses **Run Now** it runs the right tests on staging, collects proof for every
failure and drafts a Jira ticket. **Nothing reaches Jira until the tester approves it.**

**This branch is `verixa-fyp1`: version 1.** It holds the seven FYP I use cases of the SRS (UC1 to UC7).
Version 2 adds QA Memory, Suggest a Fix, Regression Comparison and Risk Trends (UC8 to UC11) in the branch
`verixa-fyp2`, which is this branch with one commit on top.

## What to read

| You want | Read |
|---|---|
| To understand the whole product, V1 and V2, in simple words | [VERIXA_GUIDE.md](VERIXA_GUIDE.md) |
| To set it up and run it with real GitHub and Jira | [START.md](START.md) |
| The Test Agent in detail | [TEST_AGENT.md](TEST_AGENT.md) |
| The Analysis Agent in detail | [AGENT_GUIDE.md](AGENT_GUIDE.md) |
| Sample files and inputs to try by hand | [samples/test-data/README.md](samples/test-data/README.md) |
| What was delivered and the test results | [FINAL_DELIVERY.md](FINAL_DELIVERY.md) |
| The detailed history of Deliverables 1 and 2 | [docs/DELIVERABLES_1_2.md](docs/DELIVERABLES_1_2.md) |

## What is in this version

| Use case | Feature | In one line | Screen |
|---|---|---|---|
| UC1 | Account and Project Setup | Sign up, link GitHub and Jira once, save the staging address | Integrations |
| UC2 | Test Library Upload | Upload Playwright specs and a Postman collection, checked before saving | Test Library |
| UC3 | Pull Request Risk Scoring | Every pull request gets a Low, Medium or High label with its reasons | Risk Analysis |
| UC4 | One Click Test Execution | Run Now picks the tests, runs them on staging and sorts every result | Test Runs |
| UC5 | Coverage Gap Test Drafting | A draft test for changed code that no test covers | Test Runs |
| UC6 | Results and Evidence View | Screenshot, trace and logs of each failure in one place | Test Runs |
| UC7 | Manual File to Jira | A ticket draft per real bug, filed only when the tester approves | Jira Tickets |

## How it works

```text
A pull request is opened      -> the Analysis Agent gives a risk label (rules decide, the model explains)
The tester presses Run Now    -> the Test Agent picks tests, checks staging, runs Playwright and Newman
Every result is sorted        -> passed, real bug, temporary error, deployment pending or skipped
For each real bug             -> the Report Agent drafts a Jira ticket with the proof
The tester approves           -> only then is the ticket filed in Jira
```

A fourth agent, the **Manager**, checks every answer an agent gives. A bad answer goes back with the reason, at
most 3 times. After that the item is marked for a person to review.

## Rules that never bend

- A run starts only when the tester presses **Run Now**.
- Nothing goes to Jira without the tester's approval.
- Tests run only on the staging address, never on the live system.
- Code that is not on staging yet is "deployment pending", not a bug. A timeout is a "temporary error", not a bug.
- The risk label comes from rules. A model cannot change it.
- Keys, tokens and passwords are removed before text is stored, sent to a model or sent to Jira.

## Set up once

You need Python 3.11 or newer and Node.js 20 or newer. In PowerShell, from the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend; npm install; npm run build; cd ..
cd runner; npm install; npx playwright install chromium; cd ..
```

Copy `.env.example` to `.env` and fill it in. Never commit `.env`.

## Run it

**The real app**, with your GitHub, Jira and database (details in [START.md](START.md)):

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000
```

**A demo copy**, with a throwaway database and no real GitHub or Jira:

```powershell
.\.venv\Scripts\python.exe tests\e2e\server.py     # http://localhost:8011/login
```

Log in with `demo@verixa.dev` and the password `Verixa-Demo-2026`.

**The staging shop for demos**, a small shop with bugs you can switch on and off:

```powershell
python staging\server.py                           # shop: http://127.0.0.1:4000   switches: /demo
```

The demo steps are in section 11 of [samples/test-data/README.md](samples/test-data/README.md).

## Test it

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_qa_units tests.test_qa_flow tests.test_qa_system
cd tests\e2e; npx playwright test --project=qa; npx playwright test --project=inputs
```

505 Python tests pass. The browser suites give 157 passed and 1 skipped on purpose. 54 inputs are checked.
Python tests use their own test database and refuse to start any other way, so the real database is never touched.

## Folders

| Folder | What is in it |
|---|---|
| `backend/` | The FastAPI server: accounts, Test Library, runs, tickets |
| `agents/` | The Analysis, Test and Report agents and the Manager |
| `frontend/` | The React dashboard |
| `runner/` | Playwright and Newman, which run the tester's tests |
| `staging/` | The demo shop |
| `samples/` | Sample specs, collections and inputs |
| `tests/` | Python tests, and browser tests in `tests/e2e/` |

## Known limits

- The risk rules were measured on 30 examples the team wrote (26 correct). Accuracy on real projects is not measured.
- There is no one command way to start a run. Run Now is the only way.
- Checking uploaded test code by its text cannot catch every trick, so each run is also isolated.
