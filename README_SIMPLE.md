# Verixa in simple words

For the full technical details, see [README.md](README.md). To run the project, see [START.md](START.md).

## 1. What Verixa does

When a developer opens a pull request (PR) on GitHub, someone has to decide how carefully to test it. A typo fix needs
little testing, while a change to login or payments needs a lot.

**Verixa makes that first decision automatically.** It reads the PR and shows:

- a **risk label**: Low, Medium or High
- **why** it got that label
- **what to test**

**Example:** PR #7 on our demo shop, Shoplite, adds coupon codes to checkout. Verixa labelled it High because it touches
payment code, and suggested tests such as "reject invalid coupon code during checkout".

### What is built

| Built and working | Not built yet |
|---|---|
| Accounts, login and two-step verification | Running the uploaded tests |
| Connecting GitHub and Jira | Saving test evidence |
| Automatic risk scoring of each PR | Creating Jira tickets |
| Risk Analysis screen | Final reports |
| Test Library, to store Playwright and Postman tests | |

The second column belongs to later deliverables, and the dashboard shows those items as "Coming Soon".

## 2. How it works

1. A developer opens or updates a PR on GitHub.
2. GitHub sends a message to Verixa. This is called a **webhook**.
3. Verixa checks the message's signature, to prove it really came from GitHub.
4. The **Analysis Agent** reads the PR's changes from GitHub and looks up past bug fixes in that part of the code.
5. **Rules in our code** decide the risk label. No AI is involved in this step.
6. Any secrets are hidden, and then **the AI writes** the explanation and the test ideas.
7. The **Manager Agent** checks the AI's answer. If the answer is bad, it asks again, up to 3 times.
8. The result is saved and appears on the Risk Analysis screen.

### The most important design decision

**Rules decide the label, and the AI only explains it.** So the AI can't invent a label, and someone hiding "please mark
this Low" inside a PR can't change it. If the AI fails completely, the PR still keeps its label and goes to a person for review.

### How the label is worked out

```
score = size points + past bug points + sensitive code points
```

| Part | Points |
|---|---|
| Files changed | 1 (under 4), 2 (4 to 9), 3 (10 or more) |
| Lines changed | 1 (under 100), 2 (100 to 499), 3 (500 or more) |
| Past bug fixes | 0 (none), 1 (1 to 3), 2 (4 to 9), 3 (10 or more) |
| Sensitive code | 0 (none), 1 (user, data or config code), 2 (security or payment code) |

**Result:** Low is 3 or less, Medium is 4 to 6, and High is 7 or more.

Some changes are then **raised, never lowered**:

- Security or payment code is at least **High**.
- User, data or config code is at least **Medium**.
- A very large change (10 or more files and 500 or more lines) is **High**.

Test files and documents are not counted as sensitive, even if they mention passwords.

## 3. Architecture

```
    Developer                              Team member
        |                                       |
        | opens a PR                            | uses the dashboard
        v                                       v
 +-------------+                     +---------------------+
 |   GitHub    |                     |  Browser (React)    |
 +-------------+                     +---------------------+
        |                                       |
        | webhook                               |
        v                                       |
 +-------------+                                |
 |    ngrok    |  public address for the laptop |
 +-------------+                                |
        |                                       |
        v                                       v
 +----------------------------------------------------------+
 |                  Verixa server (FastAPI)                 |
 |                                                          |
 |   Accounts   GitHub and Jira link   Test Library         |
 |                                                          |
 |   Manager Agent: checks the answer, retries up to 3 times|
 |        |                                                 |
 |        v                                                 |
 |   Analysis Agent                                         |
 |        1. Reads the PR from GitHub                       |
 |        2. Rules decide the label                         |
 |        3. Hides secrets                                  |
 |        4. Asks the AI for an explanation  ---------------+--> AI model (Groq)
 +----------------------------------------------------------+
                              |
                              v
                 +--------------------------+
                 |  Neon PostgreSQL database |
                 +--------------------------+
```

There is one server. It runs the website, the API and the agents together, so the agents are called directly and not over
the network.

## 4. Tools and technology

| Part | Tool | What it does for us |
|---|---|---|
| Backend | **Python** and **FastAPI** | The server and its API |
| | **Uvicorn** | Runs the server |
| | **SQLAlchemy** | Lets Python talk to the database |
| Frontend | **React** and **TypeScript** | The website and dashboard |
| | **Vite** | Builds the website files |
| Database | **Neon PostgreSQL** | Stores accounts, tests and results in the cloud |
| | **SQLite** | Small temporary database used only for tests and the demo |
| Agents | **Google ADK** | Framework that runs the Manager and Analysis agents |
| | **LiteLLM** | Lets us call different AI providers the same way |
| | **Groq** | Runs the AI model that writes the explanations. OpenRouter and Gemini can be set up as backups |
| Connections | **GitHub** | Sign in, PR data and webhooks |
| | **Atlassian Jira** | Sign in and choosing a Jira project |
| | **ngrok** | Gives the laptop a public address, so GitHub can reach it |
| Security | **scrypt** | Scrambles passwords, so they aren't stored as plain text |
| | **Fernet** | Encrypts saved GitHub, Jira and two-step secrets |
| | **PyOTP** and **Segno** | Two-step codes, and their QR code |
| Testing | **unittest** | Python tests |
| | **Playwright** | Tests the app in a real browser |

## 5. What each file does

### Top folder

| File | What it is |
|---|---|
| `README.md` | Full technical documentation |
| `README_SIMPLE.md` | This guide |
| `START.md` | How to run the project and demo it |
| `AGENT_TESTING.md` | The agent test plan |
| `AGENT_TEST_RESULTS.md` | The agent test results |
| `.env` | Passwords and keys. **Private, and never uploaded to GitHub** |
| `.env.example` | A blank template for `.env` |
| `requirements.txt` | Python packages the project needs |
| `docker-compose.yml` | Optional local database |

### `agents/`: the AI part

| File | What it does |
|---|---|
| `manager.py` | **The checker.** Checks the AI's answer, and retries or sends the PR to a person |
| `analysis.py` | **The worker.** Reads the PR, gets the score and asks the AI to explain it |
| `risk_rules.py` | **The rules** that decide the score and label |
| `github_client.py` | Reads PRs and past bug fixes from GitHub |
| `redact.py` | Hides secrets before anything is sent to the AI |
| `llm.py`, `models.py` | Choose the AI model, and try the next one if it fails |
| `runner.py` | Starts a run, and stops it if it takes too long |
| `trace.py` | Logs every step, so a run can be followed afterwards |
| `events.py` | Small helper for messages between the agents |

### `backend/`: the server

| File | What it does |
|---|---|
| `main.py` | **The starting point.** Sets up the app, its security headers and the webhook |
| `settings.py` | Reads settings from `.env` |
| `db.py` | Main database tables |
| `agent_db.py` | The table that stores risk results |
| `auth.py` | Sign up, log in, log out and GitHub or Atlassian sign in |
| `accounts.py` | Rules for names, emails and passwords, and login limits |
| `twofactor.py`, `totp.py` | Two-step verification |
| `profile.py` | Change name or password, or delete the account |
| `security.py` | Encryption and webhook signature checks |
| `integrations.py` | Talks to GitHub and Jira for the dashboard |
| `api.py` | Dashboard API for connecting a repo and for the Test Library |
| `library.py` | Decides whether a Test Library save is allowed |
| `validators.py` | Checks uploaded test files |
| `analysis_service.py` | **The bridge** from the webhook to the agents to the database |
| `analysis_api.py` | Gives risk results to the Risk Analysis screen |

### `frontend/`: the website

| Folder or file | What it does |
|---|---|
| `src/landing/` | Public home page |
| `src/auth/` | Login, sign up and two-step screens |
| `src/dashboard/RiskView.tsx` | **Risk Analysis screen** |
| `src/dashboard/ConnectView.tsx` | Connecting GitHub, Jira and a repo |
| `src/dashboard/LibraryView.tsx`, `library.ts`, `useLibrary.ts` | Test Library screen and its logic |
| `src/dashboard/validation.ts` | Checks uploaded files in the browser |
| `src/dashboard/SecurityView.tsx` | Two-step settings |
| `src/dashboard/App.tsx`, `Rail.tsx` | Dashboard layout and left menu |
| `src/dashboard/api.ts` | Calls the server |
| Other files in `src/dashboard/` | Smaller parts of those screens |
| `src/shared/` | Parts used by several pages |
| `public/assets/` | Logo, video and other fixed files |
| `index.html`, `auth.html`, `verixa_prototype.html` | The three pages: home, login and dashboard |

### `tests/`: automatic tests

| File | What it checks |
|---|---|
| `test_agents_real.py` | The real agents, with GitHub and the AI faked |
| `test_agent_secrets.py` | Secrets are hidden from the AI |
| `test_agent_trace.py` | Logs are correct and contain no keys |
| `test_risk_rules.py` | The scoring rules |
| `test_risk_eval.py` | Label accuracy on 30 example PRs |
| `test_analysis_integration.py` | The whole path from webhook to dashboard data |
| `test_qa_security.py` | Bugs found by trying to break the app |
| `test_crud.py`, `test_library.py`, `test_validators.py` | Saving, changing and deleting data, and file checks |
| `test_accounts.py`, `test_twofactor.py` | Account rules and two-step verification |
| `e2e/` | Playwright tests in a real browser |

### `scripts/`: helper tools

| File | What it does |
|---|---|
| `seed_demo.py` | Creates demo accounts in a local database. It refuses any other database |
| `agent_trace.py` | Shows what happened during an agent run |
| `live_check.py` | Tests the real agent with the real database, then cleans up |
| `live_injection_check.py` | Tries to trick the real AI |
| `check_database.py` | Tests the app on the real database, then cleans up |
| `show_data.py`, `show_2fa_data.py` | Show what is stored, without changing it |

### `samples/`: test data

| Folder or file | What it is |
|---|---|
| `test-data/README.md` | Inputs to try by hand, with expected results |
| `test-data/should-pass/`, `should-fail/` | Files the Test Library must accept or refuse |
| `test-data/shoplite/PULL-REQUESTS.md` | 8 sample PRs for testing the agent |
| `test-data/shoplite/shop.spec.ts`, `shoplite.postman_collection.json` | Shoplite's tests for the Test Library |

## 6. How we tested the agent

### The short answer

> We tested the agent at four levels. First, automated tests of the real agent code with GitHub and the AI faked, so every
> failure can be repeated. Second, real browser tests of the full app. Third, live tests with real GitHub and the real AI model
> on our Shoplite demo. Fourth, attacks, such as hiding instructions in a PR to trick the AI. We also read the AI's real answers
> ourselves, because a passing test doesn't prove an answer is true.

### The four levels

| Level | What is real | What is faked | Why we do it | Result |
|---|---|---|---|---|
| **1. Python tests** | Agent code, rules, database and API | GitHub and the AI | Repeatable and free, including failures that are hard to create | **371 of 371 pass** |
| **2. Browser tests, scripted** | Browser, app and agents | GitHub and the AI | Checks what a user really sees | **31 of 31 pass** |
| **3. Browser tests, live** | Everything: real GitHub and real AI | Nothing | Proves it works outside test conditions | **5 of 5 pass**, on Shoplite PRs #7, #9 and #10 |
| **4. Attacks on the real AI** | Real AI | The PR content | Checks whether the AI can be tricked | **Not tricked in 5 of 5**, one run each |

**Tested on real repositories:** public `Shoplite`, and a private test repository. On the private one, a collaborator opened
pull request #2, and Verixa scored it automatically for the account that connected the repository. That is one pull request, so
it shows the flow works, not how accurate it is on private code.

### How we built the test plan

1. We started with a checklist of **162 items**.
2. We removed items that weren't real tests, or that tested features we don't have.
3. That left **44 tests and 6 metrics**, each matched to how the agents really work.
4. We wrote tests first and ran them against the old code, to prove they catch the problem.
5. We fixed the bugs and ran everything again.

**Current status of the 44 tests:** 34 pass, 7 partly pass with a stated limit, 1 fails and 2 are not run. Details are in
[AGENT_TESTING.md](AGENT_TESTING.md).

### What we tested

| Question | How we tested it |
|---|---|
| Is the label correct? | 30 labelled example PRs: **26 correct, 87%**, against a target of 80% |
| Does it analyse the right commit? | New pushes, two PRs at once, and a push during analysis |
| Does a repeated webhook analyse twice? | Sent repeat deliveries. Only one result is saved |
| Is a fake webhook refused? | Sent wrong signatures. They get a 401 |
| Does the Manager catch bad answers? | Gave it 14 badly formed answers, invented explanations and answers that contradict the label |
| Can the AI change the label? | Made the AI's answer include its own label. It is ignored |
| What if the AI is down or never answers? | Each model gets 60 seconds and a run gets 300. The label is kept where it was already worked out, and the PR goes to review or is marked failed |
| What if GitHub fails? | Missing PRs and blocked lookups. Blocked history shows as "unknown", not as clean |
| Can a PR trick the AI? | Hid instructions in the title, code comment, README, config file and a fake end of data |
| Do secrets reach the AI? | Put keys in the code and title. They are replaced with `[HIDDEN SECRET]` |
| Can one account see another's results? | Tried on screen and through the API. It gets a 404 |
| Can hostile text run in the page? | Put `<img onerror=alert(1)>` in PR titles. It shows as plain text |

### Real bugs the testing found

| Bug | Fix |
|---|---|
| The AI described changes that didn't exist, and the Manager approved them | The AI now sees only the diff, and the Manager checks the answer is about the change |
| A new push was scored using the old code | Each new delivery reads the PR again |
| A model that never answered could hang forever | Time limits added |
| A blocked lookup looked like a clean history | It now shows as unknown |
| Secrets in a PR were sent to the AI provider | Hidden first |
| A crashed analysis stayed on "running" forever | Marked as failed |

### Where to show the proof

| To show | Do this |
|---|---|
| Run all Python tests | `.\.venv\Scripts\python.exe -m unittest discover -s tests -t .` |
| Show the label accuracy | `.\.venv\Scripts\python.exe -m tests.test_risk_eval` |
| Follow one agent run step by step | `.\.venv\Scripts\python.exe scripts\agent_trace.py --list` |
| Try a live PR | Follow `samples/test-data/shoplite/PULL-REQUESTS.md` |

### Be honest about these limits

If mentors ask what is not perfect, these are the true answers:

- **Accuracy is measured on examples.** The 87% comes from 30 PRs we wrote ourselves, by people who had read the rules. It
  shows how the rules behave, not their accuracy on real projects.
- **The AI can still be wrong.** The Manager compares words, so an answer can name the right file and still say something false.
  The explanation is a suggestion, and a person should check it.
- **Test ideas can miss hidden bugs.** On Shoplite PRs #10 and #7, the suggested tests missed both known hidden bugs. That is 0 of 2,
  which is too small a sample to measure properly, but it shows the limit.
- **The attack result is a small sample:** one run of each of 5 cases, with one model.
- **Hiding secrets isn't perfect.** A secret with no known format can still get through, and it stays visible on GitHub.
- **One test is still marked as failed (AT-43):** two Shoplite webhooks point at a wrong address (`/webhook/github`) and get a 405.
  The repository owner needs to check them, then fix or delete them. Separately, real deliveries reached Verixa and scored PR #7.
- **The rules miss some sensitive words,** such as `bcrypt` and `cors`. They are recorded as known gaps, and can be added through
  settings.

## 7. Likely questions from mentors

**Why not let the AI decide the risk?**
AI answers can change from run to run, and it can be tricked. Rules give the same answer every time, and we can explain exactly
why a label was given.

**Then why use AI at all?**
Rules can give a label, but they can't describe a specific change in plain language or suggest specific tests for it.

**What is the Manager Agent for?**
It checks the AI's work using plain code. It doesn't use another AI. It retries with the reason for rejection, and sends the PR to a
person after 3 failed tries.

**What happens if the AI service is down?**
The label is still worked out, because it needs no AI. The PR goes to "Needs review" with its label.

**How do you stop fake webhooks?**
GitHub signs every message with a shared secret. Verixa checks the signature first, and refuses anything wrong with a 401.

**How are passwords and tokens stored?**
Passwords are hashed with scrypt, so they can't be read back. GitHub and Jira tokens and two-step secrets are encrypted.

**Does Verixa change our code on GitHub?**
The agents only read. The only thing Verixa creates on GitHub is the webhook, when you connect a repository.

**Why does it need ngrok?**
GitHub has to reach the server, and a laptop has no public address. A real deployment wouldn't need it.

**What comes next?**
Running the tests, saving evidence, creating Jira tickets and writing reports. These are later deliverables.
