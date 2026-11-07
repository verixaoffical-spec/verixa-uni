# Verixa: Deliverable 1 + Deliverable 2 (risk scoring)

One application that joins the completed Deliverable 1 work from **official_ui-main** with the
completed Deliverable 2 risk-scoring work from **multi-agents**.

A pull request opened on a connected repository is scored automatically: rules in code decide the
risk label, the Analysis Agent writes the reasoning and the test areas, the Manager validates that
output and retries with feedback, and the result lands on the Risk Analysis screen in the
dashboard. Accounts, two-step verification, the GitHub and Jira connection and the Test Library are
the Deliverable 1 app.

FastAPI serves both the API and the built React frontend, so there is one server and one address.
Data is stored in the shared Neon PostgreSQL database.

**New to the project? Read [README_SIMPLE.md](README_SIMPLE.md).** **To run it, follow
[START.md](START.md).** For everything changed in the `verixa-uni-v2`
branch, and why, see [section 12](#12-what-changed-in-verixa-uni-v2). For the latest additions (forgot
password, email, and live agent updates over a WebSocket), see [section 13](#13-updates-on-7-november-2026).

**Contents**

1. [What is included, and what is not](#1-what-is-included-and-what-is-not)
2. [Folder structure](#2-folder-structure)
3. [Installation and setup](#3-installation-and-setup)
4. [Environment variables](#4-environment-variables)
5. [Starting the app](#5-starting-the-app)
6. [How the Analysis Agent works](#6-how-the-analysis-agent-works)
7. [How a risk score reaches the UI](#7-how-a-risk-score-reaches-the-ui)
8. [Database](#8-database)
9. [API endpoints](#9-api-endpoints)
10. [Testing](#10-testing)
11. [Known limitations and outstanding work](#11-known-limitations-and-outstanding-work)
12. [What changed in verixa-uni-v2](#12-what-changed-in-verixa-uni-v2)
13. [Updates on 7 November 2026](#13-updates-on-7-november-2026)

---

## 1. What is included, and what is not

### Deliverable 1 — the application (from official_ui-main)

Consolidated in full, as the completed app it already was:

| Area | What it does |
|---|---|
| Accounts | Sign up and log in with email and password, or with GitHub. Name, password and account deletion in settings |
| Forgot password | A single-use reset link by email, valid for 30 minutes (section 13) |
| Two-step verification | Authenticator app codes, ten single-use recovery codes, the code step after the password |
| Sessions | Signed cookie, 14 days, `session_version` so a password change signs out every other session |
| GitHub and Jira | One sign-in links both. Repositories and Jira projects are listed and connected |
| Webhook | Created automatically on connect, pinged, and verified when GitHub's first delivery arrives |
| Test Library | Playwright specs and one Postman collection per project, with strict checks and a live preview |
| Landing page | The public site, intro video and product preview |

### Deliverable 2 — risk scoring (Phase 3, weeks 7–8)

Consolidated because the work is finished and verified in the source folders:

| Backlog task | Lead | What was reused |
|---|---|---|
| **T-031** Analysis Agent: rule-based risk score | Farheen | `agents/risk_rules.py`, `agents/analysis.py` |
| **T-033** New-module size-based scoring | Farheen | the size and floor logic in `agents/risk_rules.py` |
| **T-035** Manager Agent: validation, retry cap, escalation | Farheen | `agents/manager.py` |
| **T-030** GitHub PR diff fetch | Arisha (Farheen support) | `agents/github_client.py` — needed by T-031 |
| **T-032** Module defect history query | Arisha (Farheen support) | `count_fix_commits`, `count_defects` — needed by T-031 |

**T-035 is included** because the Analysis Agent's result object is produced *by* the Manager, not
by the worker: `agents/manager.py` is what validates the JSON, feeds errors back for another
attempt, caps the attempts at three and escalates to `needs_human_review`. Without it there is no
analysis result to show. It is Farheen's task and it is implemented, so it is in scope.

### Deliberately not included

| Task | Why |
|---|---|
| **T-034** Yes/no risk questions + majority vote of 3 | Not implemented anywhere in multi-agents. The agent uses deterministic rules plus a single model call for the explanation only. Still TODO |
| Test & Execution Agent (`test_agent/`, `manager_agent/test_phase.py`) | Still in its testing phase, and Deliverable 3 scope. `tests/test_analysis_integration.py` asserts it has not crept in |
| Test run, evidence, Jira filing, drafted tests | Deliverables 3 to 5, not started |

---

## 2. Folder structure

```
mid/
  backend/                  FastAPI: the app plus the agent integration
    main.py                 app, pages, static frontend, the GitHub webhook
    settings.py  db.py      settings and the five app tables         (Deliverable 1)
    auth.py  twofactor.py   sign in, OAuth, two-step verification    (Deliverable 1)
    profile.py  accounts.py account settings, password rules         (Deliverable 1)
    api.py                  session, connect, Test Library           (Deliverable 1 *)
    library.py  validators.py  save rules and file checks            (Deliverable 1)
    security.py  totp.py    encryption, webhook signature, TOTP      (Deliverable 1)
    integrations.py         GitHub and Atlassian calls               (Deliverable 1)
    __init__.py             NEW: loads .env into the process, for the agent
    agent_db.py             NEW: the risk_assessments table
    analysis_service.py     NEW: webhook -> agent -> database
    analysis_api.py         NEW: /api/analysis for the dashboard
    live.py                 NEW: /api/live, the WebSocket that pushes agent steps to the dashboard
    password_reset.py       NEW: forgot password and reset password
    mailer.py               NEW: sends email over SMTP, or prints it when SMTP is not set
  agents/                   the Analysis Agent, reused from multi-agents
    risk_rules.py           T-031 / T-033, unchanged
    analysis.py             T-031, the worker        (imports, a token parameter, the prompt fix in section 12)
    manager.py              T-035, plus a check that the explanation is about the changed code
    github_client.py        T-030 / T-032            (per-account token, no create_webhook)
    llm.py  events.py  models.py   shared plumbing, unchanged
    runner.py               drives ADK               (imports + a token parameter)
  frontend/                 React + TypeScript, built with Vite
    src/dashboard/RiskView.tsx   NEW: the Risk Analysis screen, with the live agent activity panel
    src/auth/PasswordReset.tsx   NEW: the Forgot password and Choose a new password pages
    src/dashboard/risk.css       NEW: its styles
    src/dashboard/api.ts         + the analysis calls and types
    src/dashboard/Rail.tsx       Pull Requests is now a real screen, not Coming Soon
    src/dashboard/App.tsx        + the risk view and its #risk address
    src/shared/urlError.ts       NEW: only real sign in messages are shown from the address bar
    public/assets/theme-init.js  NEW: the saved theme, moved out of the page for the security policy
  tests/                    263 tests
    test_risk_rules.py           NEW: the rule engine
    test_analysis_integration.py NEW: webhook -> agent -> database -> API
    test_qa_security.py          NEW: every bug found while trying to break the app
    test_risk_eval.py            NEW: T-037, the labelled eval set
    ... the five Deliverable 1 suites
  scripts/                  database checks
    check_database.py       D1 on the real database   (extended: fingerprints whichever agent tables exist)
    live_check.py           NEW: D2 end to end on the real database with the real agent
    seed_demo.py            NEW: demo accounts on a local SQLite file, to try every screen without OAuth keys
    show_data.py  show_2fa_data.py   read-only views, unchanged
  samples/                  a spec and a collection that pass every check
    test-data/              files that must pass, files that must fail, and a guide to testing by hand
    test-data/shoplite/     Shoplite's tests for the Test Library, and sample pull requests for the agent
  .env.example  requirements.txt  docker-compose.yml  README.md  START.md
```

\* `api.py` has one addition: `remove_project` also deletes the project's risk assessments, so
disconnecting or deleting an account does not leave rows pointing at a project that is gone.

Nothing in `official_ui-main/` or `multi-agents/` was modified. Both folders were SHA256
fingerprinted before and after this work and are byte-identical.

---

## 3. Installation and setup

Windows PowerShell, from this folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

cd frontend; npm install; npm run build; cd ..

copy .env.example .env     # then fill it in, see section 4
```

The server **refuses to start until the frontend is built**. Run `npm run build` again after
changing anything in `frontend/`.

### One-time setup outside the code

Three things to register once: the tunnel, a GitHub **OAuth App**, and an Atlassian OAuth 2.0 app.
Everything below assumes the project's static ngrok domain:

```
https://cognition-skimmer-launder.ngrok-free.dev
```

Substitute your own if it differs. Every URL in this section is built from `PUBLIC_URL`, so it has
to match character for character.

#### a. ngrok

Free ngrok accounts include **one permanent static domain** (dashboard.ngrok.com → Domains). Use
it: with an ephemeral tunnel the URL changes on every restart, which breaks the OAuth callbacks
*and* leaves every webhook already created on GitHub pointing at a dead address.

```powershell
ngrok config add-authtoken <token>          # once per machine
ngrok http 8000                             # auto-uses your static domain if you have exactly one
ngrok http 8000 --url https://YOUR-DOMAIN.ngrok-free.dev   # or pin it explicitly
```

The free tier shows browsers a "You are about to visit…" interstitial. Click **Visit Site** once
per session. It does not affect GitHub's webhook deliveries, which are not browser requests.

Read the public URL back without opening the dashboard:

```powershell
(Invoke-RestMethod http://127.0.0.1:4040/api/tunnels).tunnels[0].public_url
```

#### b. GitHub OAuth App

**Settings → Developer settings → OAuth Apps → New OAuth App.** Not *GitHub Apps* — see the
warning below.

| Field | Value |
|---|---|
| Application name | anything, e.g. `Verixa (dev — Farheen)` |
| Homepage URL | `https://cognition-skimmer-launder.ngrok-free.dev` |
| Authorization callback URL | `https://cognition-skimmer-launder.ngrok-free.dev/auth/github/callback` |

Then **Generate a new client secret** — GitHub shows it only once — and put both values in `.env`
as `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`.

> **Use an OAuth App, not a GitHub App.** They look similar in the UI and both offer a client ID
> and secret, but the client ID gives it away: OAuth Apps start with `Ov` or are 20 hex characters,
> GitHub Apps start with `Iv`. A GitHub App will not work here, because:
> * it ignores the `scope=repo` parameter `integrations.py:54` sends — permissions come from the
>   app's own configuration instead;
> * its token only sees repositories where the app has been *installed*, so `list_repos`, which
>   keeps only repositories with `permissions.admin`, is likely to return an empty dropdown.

Two more traps:

* **You need admin access on a repository for it to appear at all.** `list_repos`
  (`integrations.py:80`) filters to `permissions.admin`, because creating a webhook requires it.
* **One OAuth App has one callback URL.** Each developer with their own tunnel domain needs their
  own OAuth App.

#### c. Atlassian OAuth 2.0 app

You need a **Jira Cloud site** first: `atlassian_exchange` reads `accessible-resources` and takes
the first site it finds, and with none it fails with *"No Jira site found on this Atlassian
account"*. A free site from atlassian.com/software/jira is enough.

**developer.atlassian.com/console/myapps → Create → OAuth 2.0 integration.** The scopes and the
callback live on two different pages:

1. **Permissions** → **Jira API** → *Add*, then *Configure* → the **Classic scopes** tab → tick
   `read:jira-work`, `write:jira-work`, `read:jira-user`. These are the three in `ATLASSIAN_SCOPE`
   (`integrations.py:13`). Classic, not Granular — the code asks for the classic names.
   `offline_access` is not listed here; it is a standard OAuth scope requested in the authorize URL
   to get a refresh token, and needs no console setting.
2. **Authorization** → **OAuth 2.0 (3LO)** → *Configure* → Callback URL:
   `https://cognition-skimmer-launder.ngrok-free.dev/auth/atlassian/callback`
3. **Settings** → *Authentication details* → copy the **Client ID** and **Secret** into
   `ATLASSIAN_CLIENT_ID` and `ATLASSIAN_CLIENT_SECRET`. Atlassian lets you re-reveal the secret
   later, unlike GitHub.

While the app is in development mode **only the Atlassian account that owns it can authorize it** —
anyone else sees *"You don't have access to this app"*. Fix it on the **Distribution** page by
setting it to Sharing, or let each developer create their own app.

#### d. The webhook

There is nothing to register by hand. `/api/connect` creates the pull request webhook itself
(`ensure_webhook`), pings it, and updates its own hook rather than duplicating it on reconnect.
For reference, if you ever add one manually: payload URL
`https://cognition-skimmer-launder.ngrok-free.dev/webhooks/github`, content type
`application/json`, secret = `WEBHOOK_SECRET` from `.env`, events = **Pull requests** only.

#### e. Checking the credentials without a browser

GitHub's token endpoint validates the client ID and secret *before* it looks at anything else, so a
deliberately invalid code tells you whether the pair is right:

```powershell
.\.venv\Scripts\python.exe -c "import httpx; from dotenv import dotenv_values; v=dotenv_values('.env'); print(httpx.post('https://github.com/login/oauth/access_token', headers={'Accept':'application/json'}, data={'client_id':v['GITHUB_CLIENT_ID'],'client_secret':v['GITHUB_CLIENT_SECRET'],'code':'bad','redirect_uri':v['PUBLIC_URL']+'/auth/github/callback'}, timeout=20).json())"
```

| Response | Meaning |
|---|---|
| `bad_verification_code` | **ID and secret are both correct.** Only the fake code was rejected |
| `redirect_uri_mismatch` | ID and secret are correct, but the app's registered callback URL differs from `PUBLIC_URL` |
| `incorrect_client_credentials` | The ID and secret do not match |

#### f. After editing .env

`uvicorn --reload` watches Python files, **not `.env`**. Restart the server by hand.

And once `PUBLIC_URL` is `https`, the session cookie is marked `Secure` (`main.py:36`), so signing
in over plain `http://localhost:8000` appears to succeed but the browser drops the cookie and you
look logged out. Use the tunnel URL.

---

## 4. Environment variables

One `.env` serves the app and the agent. `backend/__init__.py` loads it into the process
environment before anything reads a setting, because the agent and litellm read provider keys
straight from `os.environ`.

| Setting | Needed for | What it is |
|---|---|---|
| `PUBLIC_URL` | OAuth, webhook | The public https address of this app (your ngrok domain) |
| `SECRET_KEY` | always | Signs the session cookie, encrypts GitHub and Atlassian tokens. Never change it once in use. At least 16 characters, or the server refuses to start |
| `WEBHOOK_SECRET` | always | What GitHub signs every delivery with. Changing it breaks existing webhooks. At least 16 characters, or the server refuses to start |
| `DATABASE_URL` | always | Neon pooled connection string, pasted as Neon gives it. The same database the agents use |
| `GITHUB_CLIENT_ID` / `_SECRET` | GitHub sign-in | From the GitHub OAuth App |
| `ATLASSIAN_CLIENT_ID` / `_SECRET` | Jira | From the Atlassian OAuth 2.0 app |
| `TOTP_ENCRYPTION_KEY` | two-step | Fernet key for two-step secrets. Never change it once in use |
| `SMTP_HOST`, `SMTP_PORT` | forgot password | The mail server, for example `smtp.gmail.com` and `587`. Empty: the reset email is printed in the server window instead of sent |
| `SMTP_USER`, `SMTP_PASSWORD` | forgot password | The sending account and its **app password**, not the normal password. For Gmail: turn on 2-Step Verification, then create one at myaccount.google.com/apppasswords |
| `MAIL_FROM` | optional | The sender shown in the email, such as `Verixa <verixa.noreply@gmail.com>`. Defaults to `SMTP_USER` |
| `GROQ_API_KEY` | the explanation | At least one provider key. **The risk label and score need none** |
| `OPENROUTER_API_KEY` | fallback models | Qwen3 8B and friends |
| `GEMINI_API_KEY` | last fallback | Leave unset if real repository code must not be sent to Gemini |
| `ANALYSIS_MODELS` | optional | Overrides the model chain, comma separated and tried in order |
| `HIGH_RISK_KEYWORDS` / `MEDIUM_RISK_KEYWORDS` | optional | Extra words that mark changed code as sensitive |
| `GITHUB_TOKEN` | scripts only | Fallback token. In the running app the agent uses the signed-in account's own OAuth token |
| `TEST_DATABASE_URL` | tests only | A throwaway database to run the suite on PostgreSQL. Never production |

Generate the keys with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"                      # SECRET_KEY, WEBHOOK_SECRET
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # TOTP_ENCRYPTION_KEY
```

Everyone sharing the database must use the **same `SECRET_KEY` and `TOTP_ENCRYPTION_KEY`**, or
they cannot read each other's stored tokens and two-step secrets.

Never commit `.env`. `.gitignore` already excludes it.

---

## 5. Starting the app

```powershell
# terminal 1: the app
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8000

# terminal 2: the public address (GitHub and Atlassian need it)
ngrok http 8000 --url https://YOUR-DOMAIN.ngrok-free.dev
```

Open `PUBLIC_URL/login`. Signing up and logging in also work on `http://localhost:8000`, but
GitHub, Atlassian and the webhook only work through `PUBLIC_URL`.

`--reload` restarts on Python changes, but not on `.env` changes: restart by hand after editing it.

For frontend work, `cd frontend` then `npm run dev` serves the pages at `localhost:5173` with live
reload and passes API calls to the FastAPI server on port 8000 (keep it running).
`npm run typecheck` checks the TypeScript without building.

The Risk Analysis screen is the first item in the dashboard's left rail, at
`/verixa_prototype.html#risk`.

---

## 6. How the Analysis Agent works

Two steps. The first is code, the second is one model call.

**Step 1 — the risk label, decided by rules** (`agents/risk_rules.py`). No network, no model, so it
is deterministic and fully unit-tested.

```
score = size points + defect history points + sensitive area points

size points      files:  1 (<4)   2 (4-9)   3 (10+)
                 lines:  1 (<100) 2 (100-499) 3 (500+)
defect points    0 (none)  1 (1-3)  2 (4-9)  3 (10+, capped)
sensitive points 0 (none)  1 (medium)  2 (high)

label  Low (<=3)   Medium (4-6)   High (>=7)
```

Then **minimum labels** can raise it, never lower it:

* sensitive security or payment code touched → at least **High**
* user, data or config code touched → at least **Medium**
* a very large change (10+ files *and* 500+ lines) → **High**

"Sensitive" is decided from the changed file paths, and from the changed lines themselves when two
different security or payment words appear in them. Test and documentation files are ignored, so a
spec that mentions `password` never inflates the score.

**Defect history** (T-032) comes from the repository itself, whichever is higher of: bug-fix commits
on the touched folder in the last 12 months, and issues labelled `bug` that mention the module. A
module with no history is not given a default — it is scored by change size instead (T-033), and
the factor trace says so.

**Step 2 — the explanation, one model call.** The agent sends the label, the factor trace and the
trimmed diff and asks only for `{"reasoning": ..., "suggested_test_areas": [...]}`. The prompt tells
it the label is final and not to question it. Models are tried in the order of
`ANALYSIS_MODELS`, or the default chain in `agents/llm.py`; a model with no API key is skipped
instantly.

**The Manager** (`agents/manager.py`, T-035) then validates that output in plain code: valid JSON,
reasoning of a reasonable length that does not contradict the label, names a changed file or uses two
words from the changed code, and does not call the change safe, and 2 to 6 non-empty test areas, at
least half of them about the changed code. A rejected answer is sent back with the specific problems appended to the prompt. After
**three** attempts the pull request is escalated as `needs_human_review`, with the rule-based label
still attached — the label never depends on the model succeeding.

---

## 7. How a risk score reaches the UI

```
GitHub: pull_request opened / synchronize / reopened
   │
   ▼
POST /webhooks/github                         backend/main.py
   │  1. signature checked first (WEBHOOK_SECRET)      -> 401 if wrong
   │  2. projects.webhook_verified_at marked
   │  3. background task queued, 202 answered at once  (GitHub gives up after 10s)
   ▼
analyse_pull_request(payload, delivery_id)    backend/analysis_service.py
   │  one risk_assessments row per connected project, state "running"
   │  the account's GitHub token is decrypted from users.github_token
   ▼
run_manager(pr_id, token)                     agents/runner.py     ← a direct Python call
   │                                                                 no HTTP hop
   ├── AnalysisManager   validate, retry with feedback, cap at 3, escalate
   │      └── AnalysisAgent   score_pr() by rules, then one model call
   ▼
store_result(...)                             state "scored" or "needs_human_review"
   │
   ▼
GET /api/analysis/pull-requests                backend/analysis_api.py
   ▼
RiskView.tsx                                   the Risk Analysis screen
```

The agent is integrated **in process**, through ordinary function calls. There is no HTTP between
the API and the agent, because both run inside the same FastAPI application. The only HTTP in the
diagram is GitHub's delivery and the browser's calls.

**Mapping the agent output onto the screen.** `agents/analysis.py` returns a dict;
`backend/agent_db.py` stores it and `to_json()` renders it; `frontend/src/dashboard/api.ts`
declares the matching `Assessment` type.

| Agent output | Column | Shown as |
|---|---|---|
| `risk_label` | `risk_label` | the Low / Medium / High pill |
| `base_label` | `base_label` | "raised from Medium by a minimum label" |
| `score` | `score` | the Score column |
| `risk_factors` | `risk_factors` (JSON) | **Why this label**, one line per factor |
| `reasoning` | `reasoning` | **Agent reasoning** |
| `suggested_test_areas` | `test_areas` (JSON) | **Suggested test areas**, numbered |
| `module`, `modules_touched`, `files_changed`, `lines_changed`, `past_defects_in_module`, `sensitivity` | the matching columns | the chips under the detail |
| `model` | `model_used` | "explained by groq/openai/gpt-oss-20b" |
| `attempts`, `errors` | `attempts`, `errors` | the attempt count and the escalation reason |

The screen renders only what is stored. A pull request that has not been scored shows its real
state — Queued, Analysing, Needs review or Failed — never a placeholder label. The list polls every
four seconds **only while something is actually being scored**, and only while the screen is open.

While the agents work, each step also arrives **live over a WebSocket** (`/api/live`) and shows in an
activity card per pull request: received, reading the changes, the rule score, the model call, the
Manager verifying or rejecting the output, the Analysis Agent redoing the work, and the saved result.
When the run ends the list reloads by itself, so the screen has no Refresh button. See section 13.

**Design note.** `frontend/src/landing/MockDashboard.tsx` is the hardcoded product picture on the
public landing page. Its visual language — the risk pills, the stat tiles, the pull request table —
is what `RiskView.tsx` and `risk.css` rebuild against real agent data. The landing mockup itself is
left static on purpose: it is marketing shown to signed-out visitors, who have no data to show.

---

## 8. Database

One shared Neon database, the one the agents already use. Tables are created on startup and
nothing is ever altered or dropped.

**The five tables the app owns** — `users`, `recovery_codes`, `projects`, `spec_files`,
`collections` — are **unchanged**. A sixth app table, `password_resets`, was added for forgot
password (section 13). Not one agent column was added to them;
`tests/test_analysis_integration.py` asserts this.

**The one table the agent owns** is new in this folder:

### risk_assessments

One row per `(project_id, pr_number, head_sha)`. A new push to the same pull request is a new row,
so the history of how the risk moved is kept rather than overwritten.

| Column | Notes |
|---|---|
| `id` | primary key |
| `project_id` | → `projects.id`. Deleted with the project |
| `repo`, `pr_number`, `head_sha` | unique together |
| `title`, `pr_url`, `author`, `delivery_id` | pull request facts from the webhook payload |
| `state` | `queued` \| `running` \| `scored` \| `needs_human_review` \| `failed` |
| `risk_label`, `base_label`, `score` | the rule output. `base_label` is before the minimum labels |
| `module`, `modules_touched`, `files_changed`, `lines_changed`, `past_defects`, `sensitivity`, `scoring_basis` | the inputs the score was built from |
| `risk_factors` | JSON list: the factor trace |
| `reasoning`, `test_areas`, `model_used` | the model output, written only after the Manager accepted it |
| `attempts`, `errors` | the Manager's bookkeeping |
| `created_at`, `updated_at` | |

`docs/DATA_MODEL.md` splits this into `pull_requests` and `risk_assessments`. This scope is risk
scoring only, so the few pull request facts the screen needs are folded into one row. Split it when
the Test Agent arrives in Deliverable 3 and needs a real run object.

`test_runs`, `test_results` and `test_drafts` belong to the Test Agent. This app never reads or
writes them, and `scripts/check_database.py` fingerprints whichever agent tables exist and fails if
they change while it runs.

To work offline instead of Neon: `docker compose up -d` and
`DATABASE_URL=postgresql+psycopg://verixa:verixa@localhost:5432/verixa`.

---

## 9. API endpoints

Everything from Deliverable 1 is unchanged and documented in `official_ui-main/README.md`
section 6: `/auth/*`, `/auth/2fa/*`, `/api/account/*`, `/api/session`, `/api/targets`,
`/api/connect`, `/api/disconnect`, `/api/library/*`. FastAPI's interactive docs are at `/docs` on a
local `http://` address, and switched off when `PUBLIC_URL` is `https://`.

`POST /auth/relink` is new: it forgets saved GitHub and Atlassian tokens that stopped working, so
`/auth/start` asks for both again. A token GitHub or Atlassian refuses now answers **409** with a
**Link again** action, never 401, because **401 only ever means the Verixa session is gone**.

### New in this folder

| Method | Path | Body | Success | Notes |
|---|---|---|---|---|
| GET | `/api/analysis/pull-requests` | — | `{project, items[], counts, agent_available}` | Newest first, 50 by default (`?limit=`). No project connected returns an empty feed, not an error |
| GET | `/api/analysis/pull-requests/{id}` | — | one `Assessment` | 404 for another account's row, never 403 |
| POST | `/api/analysis/analyse` | `{"pr_number": 4}` | one `Assessment` | Scores a pull request now instead of waiting for a delivery. Runs the agent inline, so it takes as long as the model chain takes |

All three need an account. **401 always means the session is gone**, as everywhere else in this
app. `counts` holds `High`, `Medium`, `Low`, `total`, `pending`, `needs_review` and `failed`,
counted over the latest assessment per pull request.

Errors from `/api/analysis/analyse`: **409** no project or no linked GitHub, **502** GitHub could
not be read, **503** the agent is unavailable (`google-adk` missing), **422** a bad pull request
number.

### Added on 7 November 2026

| Method | Path | Body | Success | Notes |
|---|---|---|---|---|
| POST | `/auth/forgot` | `{"email": "..."}` | 202 | Always the same answer, whether or not the email has an account. Limited to 3 an hour per email and 10 per address |
| POST | `/auth/reset` | `{"token": "...", "password": "..."}` | 200 | **400** for a bad, used or expired link, **422** for a weak password. Ends every session of the account |
| GET | `/forgot-password`, `/reset-password` | — | the page | The reset link is `/reset-password#token=...`. The token is after `#`, so it never reaches the server's log |
| WebSocket | `/api/live` | — | messages | Needs the session cookie and a same-site Origin. Each message is one agent step: `{repo, pr, event, text, level, done}`. Closes with **4401** when signed out |

### Changed

`POST /webhooks/github` now hands `pull_request` events with action `opened`, `synchronize` or
`reopened` to the Analysis Agent in a background task. The signature check still runs first, every
other event is still answered **202** and ignored, and repeat deliveries are filtered by
`(project, pull request, head commit)`. Sending a signed test delivery by hand is unchanged —
see `official_ui-main/README.md` section 7.

---

## 10. Testing

Build the frontend first (the end-to-end tests run the real app). Then name the modules:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_validators tests.test_library tests.test_accounts `
    tests.test_crud tests.test_twofactor tests.test_risk_rules tests.test_analysis_integration `
    tests.test_qa_security tests.test_risk_eval tests.test_github_refresh tests.test_legal_pages `
    tests.test_password_reset tests.test_live tests.test_ci_check tests.test_agent_fixes tests.test_manager_matching
```

To test by hand with ready-made accounts and files, follow `samples/test-data/README.md`.

**Always name the modules. Never run `unittest discover`.** The tests drop and recreate every
table, so they use a temporary SQLite file by default and never touch `DATABASE_URL`. To run them
on PostgreSQL, point `TEST_DATABASE_URL` at a database made only for tests, such as a separate Neon
branch — never the production branch, where the agent tables live.

| File | Covers |
|---|---|
| `tests/test_validators.py` | Spec and collection checks |
| `tests/test_library.py` | Test Library save rules: new, update, delete, conflicts |
| `tests/test_accounts.py` | Name, email and password rules, hashing, throttling |
| `tests/test_crud.py` | Every create, read, update and delete through the real app |
| `tests/test_twofactor.py` | Two-step verification from setup to sign in |
| **`tests/test_risk_rules.py`** | The rule engine: size, defect and sensitivity points, the minimum labels, new-module scoring, the factor trace, edge cases |
| **`tests/test_analysis_integration.py`** | Webhook → agent → database → API, the signature and action guards, auth on every route, repeat deliveries, cleanup on disconnect and account delete, and that the Test Agent has not crept in |
| **`tests/test_risk_eval.py`** | T-037: 30 labelled pull requests scored by the real rules. Run `python -m tests.test_risk_eval` to see the score |
| `tests/test_github_refresh.py` | The GitHub token's 8 hour expiry: the clock moves forward, tokens renew on every path, and failed renewals are safe |
| `tests/test_legal_pages.py` | The Privacy and Terms pages, and two claims the policy makes about stored data |
| **`tests/test_password_reset.py`** | Forgot password: links, expiry, reuse, rate limits, sessions ending, and the email sender |
| **`tests/test_live.py`** | The live WebSocket: message wording, sign-in and same-site checks, only your own repository, a real Manager retry |
| **`tests/test_ci_check.py`** | The CI result check: reading GitHub's checks, the High floor, and CI finishing later |
| **`tests/test_agent_fixes.py`** | Dangerous removals, secrets in code, no invented code tests, and the model's concern |
| **`tests/test_manager_matching.py`** | The Manager accepts correct answers about removed checks, and still rejects unrelated ones |
| **`tests/test_qa_security.py`** | Garbage input, stored script payloads, malformed requests, cross-site requests, path tricks, security headers, unreadable or revoked tokens, worst-case upload speed, and separation between accounts |

`test_analysis_integration.py` fakes GitHub at the network boundary only — `fetch_pr` and the two
defect-history lookups. Everything inside it is the real rule engine, the real Manager with its real
retry cap, the real database writes and the real API. Two tests deliberately run with no provider
key, which proves that the rule-based label still reaches the screen when the model step cannot
happen.

Checks against the real Neon database. Both of the first two are self-cleaning: they create their
own temporary account and remove it again, even if a step fails.

```powershell
# Deliverable 1: every row the app writes, then deleted. Fingerprints the agent tables and fails
# if they change while it runs.
.\.venv\Scripts\python.exe -m scripts.check_database

# Deliverable 2: the whole risk-scoring path on the real database with the real agent.
# A signed webhook delivery -> Analysis Agent -> risk_assessments on Neon -> the dashboard's API,
# then removed. Needs GITHUB_TOKEN and a provider key. Pick the pull request with:
#   LIVE_REPO=owner/name LIVE_PR_NUMBER=4
.\.venv\Scripts\python.exe scripts\live_check.py

# Read only
.\.venv\Scripts\python.exe scripts\show_data.py        # row counts and the latest rows
.\.venv\Scripts\python.exe scripts\show_2fa_data.py    # what is stored for two-step
```

Run `live_check.py` from this folder, or set `PYTHONPATH` to it, so `backend` and `agents` import.

Frontend: `cd frontend; npm run typecheck` (no build) or `npm run build`.

The test plan for the Manager and Analysis Agents, and how to trace a run with their logs, is in
[AGENT_TESTING.md](AGENT_TESTING.md). The latest fixes and test results, including the browser tests, are in
[AGENT_TEST_RESULTS.md](AGENT_TEST_RESULTS.md).

---

## 11. Known limitations and outstanding work

### Implemented and tested

* **371 tests pass**, including 24 rule-engine tests, 26 integration tests and 70 security
  regression tests (SQLite).
* **Private and public repositories both tested for real.** See "Added on 6 and 7 November" in section 12.
* `npm run typecheck` and `npm run build` are clean.
* The server boots, serves the landing page, login and dashboard, protects the new routes with
  401, rejects unsigned webhook deliveries with 401, and returns the analysis feed.
* **Live agent run against real GitHub and a real model.** `psf/requests#6500` was fetched with a
  real token, scored Medium (5) by the rules, found **21 past bug-fix commits** in the touched
  module through the real GitHub API (T-032), and was explained by `groq/openai/gpt-oss-20b` and
  accepted by the Manager on the first attempt.
* **Live database check against the shared Neon database.** `python -m scripts.check_database`
  passes all 22 of its checks: accounts, password hashing and rotation, project connect, Test
  Library create/update/conflict/delete, two-step enrolment with encrypted secrets and ten hashed
  recovery codes, then cascading deletion. The Test Agent's tables (8 runs, 195 results, 3 drafts)
  were fingerprinted before and after and are unchanged.
* **Live end to end on Neon.** `python scripts\live_check.py` passes 20/20: a correctly signed
  webhook delivery runs the real agent, the result is written to `risk_assessments` on Neon, served
  back through `/api/analysis/pull-requests` with the factor trace round-tripping through JSON, and
  then removed again. An incorrectly signed delivery is refused with 401 and never reaches the
  agent. Afterwards the database holds exactly the rows it held before.
* `official_ui-main/` and `multi-agents/` are byte-identical to before this work (SHA256, 87 and
  40 files).

None of the above is **WORKING** in the sense docs/STATUS.md uses: that needs a PASS row written by
`scripts/verify/run.py` in docs/VERIFICATION.md, and no verification script has been run for these
tasks yet.

* **Real GitHub and Atlassian sign in, and a real delivery from github.com.** An account linked both
  through the dashboard, connected `verixaoffical-spec/Shoplite`, and had its webhook created and
  verified. GitHub's deliveries reached the app through ngrok and were answered 202. Shoplite pull
  request #7 was scored High by the real agent and saved to Neon.

### Implemented but not fully tested

* **The sample pull requests.** The 8 samples in `samples/test-data/shoplite/PULL-REQUESTS.md` were run
  through the real rules, Manager and model with GitHub faked, and all 8 got the expected label. They
  have not all been opened as real pull requests.
* **The Shoplite tests in the Test Library.** Both files pass Verixa's upload checks, but they have not
  been run. Nothing in this app runs uploaded tests until Deliverable 3.
* **The eval set against real pull requests.** See T-037 below.

### Needs the right keys

* **Saved tokens can only be read with the keys that encrypted them.** Everyone sharing the database
  must use the same `SECRET_KEY` and `TOTP_ENCRYPTION_KEY`. An account whose saved GitHub or Atlassian
  sign in cannot be read, or is refused by GitHub, gets a **Link again** button. No row is damaged.

### Outstanding backlog work

* **T-034** yes/no risk questions with a majority vote of 3 — not implemented. The agent currently
  makes one model call for the explanation only, and the label never depends on a vote.
* **T-036** the PR and risk dashboard screen is done. It is the Risk Analysis screen,
  `frontend/src/dashboard/RiskView.tsx` and `risk.css`: each pull request's label, score and state, the reasons
  for the label, the agent's reasoning and suggested test areas.
* **T-037** a first eval set is in `tests/test_risk_eval.py`: 30 labelled cases, 26 correct (87%), with
  the 4 misses listed as known gaps. The labels and changes were written for this set by someone who
  had read the rules, so they are a draft: the team should review them and add real pull requests
  before relying on the number. It measures the rule-based label, not the model's explanation.
* Deliverables 3 to 5 — test selection and running, evidence, the Report Agent and Jira filing —
  are not started. The rail still shows Test Runs, Evidence, Jira Sync and Agent Logs as
  Coming Soon.

### Smaller things

* `/api/analysis/analyse` runs the agent inline and holds the request open for as long as the model
  chain takes. Acceptable for a dashboard button, but it should move to a background task with
  polling if the chain gets slow.
* The ADK runner prints `App name mismatch detected ... implies app name "agents"` on first use.
  Cosmetic: the app name is `verixa` while the package directory is `agents`.
* Login and two-step rate limits are still counted in memory, so they reset when the server
  restarts and are not shared between processes. Run one server process until that changes.
* Logging out ends every session of the account on every device, because a session lives in its
  cookie and the shared `session_version` is what makes a stolen copy stop working.
* Uploaded specs are only checked as text, and `eval` or `child_process` can be disguised. Nothing
  in this app runs them. The Deliverable 3 test runner must run them in a sandbox.
* `about_this_change` in `agents/manager.py` catches an explanation of some other change, but it only
  needs one matching word, so it cannot prove that every statement in an explanation is correct.
* Defect history counts commits with words like `fix` or `patch` in the title, and a whole folder
  counts as one module, so busy folders such as `.github` can score high: `psf/requests#6500`
  changes 2 lines of CI and is Medium because of 21 such commits.
* Tables still come from `create_all` plus the small column-adding step in `db.py`. Alembic
  migrations are needed before the schema changes again — `risk_assessments` makes this more
  pressing, because dropping `projects` now needs the agent table dropped first.
* `agents/github_client.py` keeps a `verify_signature` helper that the app does not use; the app
  verifies signatures in `backend/security.py`. Left in place so the file stays recognisable
  against its original.
* The analysis is done once per connected project. A repository connected by several accounts is
  read once per account, each with that account's own token.
* The module name stops at the first folder after `src`, so `src/modules/auth/x.js` counts as the
  module `modules`. Labels are still right, but its defect history covers all of `src/modules`.
* A file of the maximum size takes about 1 to 4 seconds to check, so saves are limited to 20 a minute
  per account. A determined signed-in user could still keep the server busy for a short time.

---

## 12. What changed in verixa-uni-v2

The app was tested as an attacker would use it, on 5 and 6 November 2026. Each bug below was reproduced
first, then fixed, and the tests were run again after each batch of fixes.

**Results on the final code**

| Check | Result |
|---|---|
| Automated tests | 371 of 371 pass, on 7 November |
| Browser checks in real Chromium, against a local copy | 73 of 73 pass, with no alert, script error or blocked page resource |
| `scripts/check_database.py` on Neon | Passes, and the agent tables are unchanged |
| `scripts/live_check.py` on Neon, with the real agent | 20 of 20 pass |
| Agent on 11 real public pull requests after the fix | The Manager approved all 11, and each label came from the rules |
| 8 sample pull requests, with GitHub faked | 8 of 8 got the expected label |
| `npm audit` | 0 vulnerabilities |

The browser checks were a temporary script and are not in this repository.

### Bugs fixed

**Critical and high**

| Bug | Fix | Files |
|---|---|---|
| A blank `SECRET_KEY` or `WEBHOOK_SECRET` was accepted, so anyone could forge a login or a delivery | The server refuses to start with a secret under 16 characters | `backend/settings.py` |
| A token refused by GitHub or Atlassian answered 401, which sent the dashboard between log in and back in a loop, and showed a false "session ended" message | It now answers 409 with a **Link again** button that stays on screen. 401 only ever means the Verixa session is gone | `backend/integrations.py`, `backend/auth.py` (`/auth/relink`), `frontend/src/dashboard/ConnectView.tsx`, `api.ts` |
| Anyone could crash the server without logging in, using a non-ASCII webhook signature or a lone surrogate in a request | These now answer 401 or 422. Validation errors no longer repeat what was sent, which could include a password | `backend/security.py`, `backend/main.py` |
| `<script>` text was accepted as an email, and a `javascript:` link could be stored for a pull request | Both are refused. Only `https://github.com/` links are kept and shown | `backend/accounts.py`, `backend/analysis_service.py`, `frontend/src/auth/rules.ts`, `RiskView.tsx` |
| No browser protection against injected scripts | Added a Content-Security-Policy, HSTS on https, and `no-store` on API answers. The inline theme script moved to its own file | `backend/main.py`, `frontend/index.html`, `frontend/public/assets/theme-init.js` |
| Connect, Test Library saves and deletes had no check against requests from other sites | They now refuse them, like the other routes | `backend/api.py` |
| `../..` was accepted as a repository name and sent to the GitHub API | Refused before reaching GitHub | `backend/api.py` |
| A new push was scored from the previous push's diff | The cached diff is cleared for each new delivery | `backend/analysis_service.py` |
| A crash during **Analyse now** left a row on "running" for ever, and the screen kept polling | The row is marked failed | `backend/analysis_service.py` |
| **The model explained changes that did not exist.** A version bump in a linter config was described as redirect-loop logic, and the Manager approved it | The writer now sees only its instructions and the diff, and the Manager rejects an explanation that mentions nothing from the changed code | `agents/analysis.py`, `agents/manager.py` |
| Malformed collections, signed webhooks of the wrong shape, huge numbers and unreadable saved tokens each caused a 500 | Each now gets a clear answer | `backend/validators.py`, `main.py`, `api.py`, `analysis_api.py`, `analysis_service.py` |
| One upload could hold up the server: 50,000 tests in a file took 13 seconds to check | Line numbers are counted once through the file instead of from the top for each test, and saves are limited per account | `backend/validators.py`, `backend/api.py`, `frontend/src/dashboard/validation.ts` |

**Medium and minor**

| Bug | Fix | Files |
|---|---|---|
| Garbage names such as `12345` and `'; DROP TABLE users;--` were accepted | Names need letters, with simple punctuation only | `backend/accounts.py`, `frontend/src/auth/rules.ts` |
| Passwords such as `aaaaaaa1` were accepted | At least 4 different characters | same |
| `eval` and `new Function` were accepted in specs, while `page.$eval` must stay allowed | Refused, and `page.$eval` still works | `backend/validators.py`, `validation.ts` |
| Valid specs with a regular expression such as `/Bob's/` were rejected as broken | Regular expressions are recognised | same |
| `file:`, `javascript:` and `data:` addresses, and text that is not an address, were accepted in collections | Refused. `{{base url}}` and `localhost` still work | same |
| File names could hide their real name with invisible characters, or have no name at all (`..spec.ts`) | Refused | same, and `frontend/src/dashboard/library.ts` |
| Risk counts changed with the page size | Counted over every row | `backend/analysis_api.py` |
| Pull requests from a previously connected repository still showed | Only the connected repository shows | `backend/analysis_api.py` |
| A failed rerun kept showing the old explanation | It is cleared | `backend/analysis_service.py` |
| `true` was accepted as a pull request number | Only whole numbers | `backend/analysis_api.py` |
| A stolen copy of a cookie kept working after logout | Logout ends every session of the account, on every device | `backend/auth.py` |
| The signup form could be used to test which emails have accounts, with no limit | Those attempts now count towards the limit | `backend/auth.py` |
| `/login?error=any text` showed that text on the page, which could be used for phishing | Only real sign in messages are shown | `frontend/src/shared/urlError.ts`, `AuthPage.tsx`, `App.tsx` |
| New rows showed "5h ago" on SQLite | Times now state that they are UTC | `backend/agent_db.py` |
| A link to `#risk` could open the wrong screen | The address is read after loading | `frontend/src/dashboard/App.tsx` |
| Empty repository and Jira lists gave no lasting reason | A message stays above the lists | `frontend/src/dashboard/ConnectView.tsx` |
| Risk rows could not be opened from the keyboard | Tab and Enter work | `frontend/src/dashboard/RiskView.tsx` |
| The **Analysed** and **Score** headers did not line up with their values | They now line up | `frontend/src/dashboard/risk.css` |
| With no GitHub token, the agent sent an empty `Bearer` header, which GitHub refuses | The header is left out, so public repositories can be read | `agents/github_client.py` |
| Other small gaps: `/docs` public on https, a request with no size could skip the size limit, a trailing slash in `PUBLIC_URL`, `agent_available` always true, a long GitHub name, a reply from GitHub that is not JSON | Each one is handled | `backend/main.py`, `settings.py`, `analysis_api.py`, `auth.py`, `integrations.py` |

### Added on 6 and 7 November

| Change | What it does | How it was checked |
|---|---|---|
| **GitHub token renewal** | GitHub tokens last 8 hours, which was why **Link again** kept appearing. Verixa now saves the refresh token and renews the token itself, 10 minutes early | 22 tests that move the clock forward. On real GitHub, two forced renewals in a row, with GitHub accepting each new token and the private repository still listed |
| **Privacy Policy and Terms of Service** | New pages at `/privacy` and `/terms`, written from what the code stores. The footer links now work | 4 tests and browser checks on desktop and phone. Not reviewed by a lawyer |
| **Product video** | Risk scoring moved from "coming next" to a real chapter: a mock-up of opening a pull request on GitHub, then the real Risk Analysis screen with sample data. The cursor is smoother. Now 1:55 | Frames reviewed, and the chapter played in Edge |
| **T-036** | The Risk Analysis screen is recorded as delivered | Decided by the team |

**Tested on real repositories**

| Repository | Result |
|---|---|
| `verixaoffical-spec/Shoplite`, public, connected by the owner | Pull requests scored automatically through the webhook |
| A private test repository, connected by the owner | The webhook was verified. Pull request #2, opened by the collaborator `Arisha004`, was scored automatically: Low, score 2, with the real model |

This is one pull request on the private repository, and it changed 1 file. The result appears in the account that connected
the repository, not in the collaborator's own Verixa account. A collaborator without admin access cannot connect a repository,
because `list_repos` leaves it out and GitHub refuses the webhook. That part comes from the code, and was not tried on GitHub.

**Still open**

* An account linked before the renewal fix has no refresh token until it links once more. `Arisha004` still needs this.
* The token has not yet been left for a real 8 hours. The renewal was forced by marking it as expired.
* An expired Atlassian refresh token answers 403, which shows an error instead of **Link again**.
* When GitHub refuses a token, the Risk Analysis row says the Manager rejected the output, with no **Link again** button.

### Behaviour changes to know about

* Logging out signs the account out on **all** devices.
* Emails must use plain English letters and numbers, to block look-alike letters. An existing account with
  an address like `josé@example.com` could no longer log in.
* Names can no longer contain digits.
* `SECRET_KEY` and `WEBHOOK_SECRET` must be at least 16 characters.
* `/docs` only exists when `PUBLIC_URL` is not https.
* Test Library saves are limited to 20 a minute per account, with at most 50 files in a request.
* GitHub tokens last 8 hours, so Verixa now saves the refresh token and renews them itself, 10 minutes early. This adds
  `github_refresh` and `github_expires_at` to `users`, added automatically at startup. An account linked before this
  change must press **Link again** once. Everyone sharing a database must run this code.

### New files

| File | What it is |
|---|---|
| `START.md` | Step by step instructions to run the project and show it to mentors |
| `tests/test_github_refresh.py` | 22 tests that move the clock past the GitHub token's 8 hours |
| `frontend/public/privacy.html`, `terms.html`, `assets/legal.css`, `tests/test_legal_pages.py` | The Privacy Policy and Terms of Service pages, and their tests |
| `tests/test_qa_security.py` | 70 regression tests for the bugs above |
| `tests/test_risk_eval.py` | T-037: 30 labelled pull requests, 87% correct, with the 4 misses recorded |
| `scripts/seed_demo.py` | Demo accounts on a local SQLite file. It refuses any other database |
| `samples/test-data/README.md` | Inputs and expected results for testing by hand |
| `samples/test-data/should-pass/`, `should-fail/` | Upload files that must be accepted or refused |
| `samples/test-data/shoplite/PULL-REQUESTS.md` | 8 sample pull requests for testing the agent on Shoplite |
| `samples/test-data/shoplite/shop.spec.ts`, `shoplite.postman_collection.json` | Shoplite's tests, in the form the Test Library accepts |
| `frontend/src/shared/urlError.ts`, `frontend/public/assets/theme-init.js` | Described in the tables above |

### Other changed files

* `frontend/package.json`, `package-lock.json`: Vite 5.4 to 6.4, a build tool only, to clear the `npm audit` warnings.
* `tests/__init__.py`: longer test secrets, for the new 16 character rule.
* `tests/test_crud.py`: resets the new save limit between tests.
* `.gitignore`: also ignores `*.db`, for the local demo database.

### Not in this repository

`.env` holds the passwords and keys and is never committed. Each person keeps their own copy, using
`.env.example` as the guide. Agent keys and app credentials are all in that one file.

---

## 13. Updates on 7 November 2026

### Forgot password

People who forget their password can now reset it themselves.

1. On the login page, **Forgot password?** opens a page that asks for the email.
2. Verixa emails a link that works **once** and expires after **30 minutes**. Asking again replaces the old link.
3. The link opens **Choose a new password**. The sign up password rules apply, and the password is typed twice.
4. Saving it signs the account out everywhere. Two-step verification still asks for its code at the next log in.

Safety built in: the answer is the same whether or not an email has an account, only a SHA-256 hash of
the link is stored, requests are rate limited, cross-site requests are refused, and the token sits after
`#` in the link, so it never reaches server or tunnel logs and is removed from the address bar on load.

**Email** is sent with **SMTP** over an encrypted (STARTTLS) connection, through the mail account set in
`.env` (section 4). We use Gmail with an app password, sending from `verixa.noreply@gmail.com`. If
`SMTP_HOST` is empty, nothing is sent and the email is printed in the server window instead.

Files: `backend/password_reset.py`, `backend/mailer.py`, `frontend/src/auth/PasswordReset.tsx`, the new
`password_resets` table in `backend/db.py`, and a **Forgot password?** link in `AuthPage.tsx`. Deleting an
account also deletes its reset links.

### Live agent updates over a WebSocket

The proposal (section 5.5) and the SRS (section 3.4) plan a WebSocket that pushes live run status to the
dashboard. It now exists at `/api/live`.

* Every step the Manager and the Analysis Agent write to their trace log becomes one short message, pushed
  to the dashboards connected to that repository. Nothing new is stored.
* The Risk Analysis screen shows a card per pull request number while it is analysed, for example
  "Manager agent rejected the output (attempt 1 of 3)" then "Analysis agent is doing the work again
  (attempt 2 of 3)". **Analyse now** shows the same steps.
* A page opened in the middle of a run still gets the steps from the last 10 minutes.
* Only a signed-in page on this site can connect, and it only receives its own repository's steps.
* The connection pings every 25 seconds so ngrok does not close it, and reconnects by itself after a drop.

Files: `backend/live.py`, `agents/trace.py` (a listener hook), `agents/manager.py` (a `manager.retry`
step), and `RiskView.tsx`, `api.ts` and `risk.css` in the dashboard.

### CI result check: catching broken code

A small change can still break the code, for example by removing a function that other files call. Word rules
cannot see that, but the repository's own CI can. So the Analysis Agent now reads the CI result of the pull
request's commit from GitHub (GitHub Actions check runs, and commit statuses from older CI).

* **CI failing** raises the label to **High**, with the reason "the build or tests fail on this commit" and the
  names of the failing checks. This stays rule based, as the SRS requires.
* **Passing, still running or no CI** never changes the label. It is recorded as one `ci:` line in the factors.
* CI usually starts at the same moment as the pull request, so the first score often sees it still running.
  The webhook now also receives GitHub's **`check_suite`** event. When CI finishes, Verixa reads the result
  again and raises the saved label if it failed, without running the agents again. The label is never lowered.
* The live panel shows "Analysis agent checked CI" and "CI finished and is failing, so the risk was raised to High".
* **Existing repositories:** click **Connect** again on Integrations once, so the webhook also subscribes to
  `check_suite`. Repositories without CI simply show "no checks run on this commit".
* `AGENT_CI_CHECK=0` turns the CI read off. The tests do, so they never call GitHub.

Files: `agents/github_client.py` (`ci_status`), `agents/risk_rules.py` (`ci_factor` and the High floor),
`agents/analysis.py`, `backend/analysis_service.py` (`apply_check_suite`), `backend/main.py`,
`backend/integrations.py` (the webhook events) and `backend/live.py`. Tests: `tests/test_ci_check.py`, 18 of 18 pass.

### Agent evaluation and three fixes

`scripts/agent_eval_check.py` runs the real Manager, Analysis Agent and model on 16 positive, negative and edge-case
pull requests (GitHub faked) and checks the answers for invented files and code, unsupported claims, wrong labels,
obeyed injections and leaked secrets. The results, with every answer, are in `AGENT_EVAL_REPORT.md`. It found:

1. **Dangerous removals and secrets scored Low.** New rules in `agents/risk_rules.py` (`risky_removals`): removing a
   login or permission check or a security setting gives **High**, removing input checks, error handling or test cases
   gives **Medium**, and a key or password added to the code gives **High**. A check that is only moved does not count.
2. **Invented code when none was shown.** For images, moved files and empty commits the prompt now says there is no
   code to describe, and the Manager rejects test areas about return values, errors, parsing or routes.
3. **The model defended labels it thought were wrong.** It may now add a **concern**, one sentence naming the changed
   line. The rule label never changes. The concern is stored in a new `risk_assessments.concern` column, added at
   startup, and shown on the Risk Analysis screen as "The agent questions this label".

It also found a Manager bug: correct answers about a removed login check were rejected, because "unauthenticated" did
not count as `isAuthenticated`. Fixed in `agents/manager.py`. Tests: `tests/test_agent_fixes.py` (15) and
`tests/test_manager_matching.py` (3). The labelled set of 30 pull requests still scores 26 of 30.

### Risk Analysis screen

The **Refresh** button was removed. The list reloads by itself when a run ends, and polls while anything is
being scored. A **Live updates on** chip shows the WebSocket is connected.

### Testing added

| Check | Result |
|---|---|
| `tests/test_password_reset.py` | 22 of 22 pass |
| `tests/test_live.py` | 12 of 12 pass, including a real Manager retry |
| Existing login, two-step, security and data suites | 160 of 160 pass |
| Browser tests, `tests/e2e/agents.spec.ts` | Pass, including two new live update tests and a check that another account receives nothing |
| Forgot password QA in a real browser, `tests/e2e/forgot_password.spec.ts` | 56 of 57 pass. 1 blocked: delivery to a real mailbox, since SMTP was not set during the run |

The forgot password QA covers navigation, email checks, email content, links, password rules, the whole
journey proved by logging in, security, and read-only database checks. Its full report is
`FORGOT_PASSWORD_QA_REPORT.md`. To run it again:

```powershell
cd tests\e2e
npx playwright test --project=forgot
node fp_report.mjs
```

The browser test server writes emails to a test inbox file instead of sending them, and
`tests/e2e/db_check.py` reads the test database without ever printing a hash or a token.

### Other changes

* `.gitignore` keeps documents (`*.docx`, `*.pdf` and similar), Word's `~$` files and `tests.txt` out of Git.
* `.env.example` lists the email settings.
