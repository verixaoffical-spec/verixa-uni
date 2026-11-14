# Run Verixa

Verixa scores the risk of every pull request on a connected GitHub repository and shows the result on a dashboard.
These steps are for Windows PowerShell, from the project folder.

## Quick start

Use this when the project is already set up. You need **two PowerShell windows**, and both must stay open.

**Window 1: the app**

```powershell
cd D:\d\verixa-final
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000
```

Wait for `Application startup complete`.

**Window 2: the public address, which GitHub and Jira need**

```powershell
D:\d\copy\ngrok\ngrok.exe http 8000 --url https://sedate-thicket-eclipse.ngrok-free.dev
```

Wait for `Session Status  online`. On another computer, use the path where ngrok is installed there.

**Open the app:** <https://sedate-thicket-eclipse.ngrok-free.dev/login>

ngrok shows a warning page on the first visit. Press **Visit Site**.

To stop, press `Ctrl+C` in both windows.

Only one computer can use this ngrok address at a time. Run it from the computer you are presenting on, and stop it
everywhere else.

## First-time setup

Do this once on each computer.

**1. Install these:** [Python 3.12](https://www.python.org/downloads/), [Node.js 20 or newer](https://nodejs.org/) and
[ngrok](https://ngrok.com/download).

**2. Set up ngrok.** Copy your authtoken from the [ngrok dashboard](https://dashboard.ngrok.com/get-started/your-authtoken):

```powershell
D:\d\copy\ngrok\ngrok.exe config add-authtoken YOUR_TOKEN
```

**3. Install the project:**

```powershell
cd D:\d\verixa-final
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend; npm install; npm run build; cd ..
cd runner; npm install; npx playwright install chromium; cd ..
```

`runner/` holds Playwright and Newman, which run the tester's tests when **Run Now** is pressed.

Run `npm run build` again after any change in `frontend/`.

**4. Add the `.env` file** to the project folder. It holds passwords and keys, so it is not in git. Get it from a team
member, or copy `.env.example` and fill it in. Never commit or share it.

**5. Check the GitHub and Atlassian apps** use these callback addresses:

- `https://sedate-thicket-eclipse.ngrok-free.dev/auth/github/callback`
- `https://sedate-thicket-eclipse.ngrok-free.dev/auth/atlassian/callback`

## Demo for mentors

1. **Landing page:** open the main address and show the product overview.
2. **Sign up or log in:** use a real email and password, or **Continue with GitHub**.
3. **Validation:** on the sign up page, try the name `<script>alert(1)</script>`, the name `12345` or the password
   `aaaaaaa1`. Each one is refused with a clear message.
4. **Connect:** open Integrations, approve GitHub and Atlassian, choose a repository and a Jira project, then press
   **Connect and create webhook**. The steps should end with `Test delivery received from GitHub`.
5. **Test Library:** upload files from `samples/test-data/should-pass/`, then press **Confirm import**. Upload files from
   `samples/test-data/should-fail/` to show them refused, each with its reason.
6. **Risk Analysis, automatic:** open or push to a pull request on the connected repository. Within a few seconds it appears
   on the Risk Analysis screen (top icon in the left rail). Ready-made examples for Shoplite are in
   [samples/test-data/shoplite/PULL-REQUESTS.md](samples/test-data/shoplite/PULL-REQUESTS.md).
7. **Risk Analysis, on request:** enter a pull request number and press **Analyse now**.
8. **Explain a result:** click a row to show why it got its label, the agent's reasoning and the suggested test areas.

**How to explain it:** rules in code decide the risk label, so the score can be checked and repeated. The AI model only
writes the explanation and the test areas, and the Manager checks that output and retries up to three times. If the model
fails, the pull request goes to human review and keeps its rule-based label.

## Backup demo without GitHub or Jira

Use this if the internet, GitHub or ngrok fails. It uses a temporary local database, so your real data is not touched.
Stop the app in Window 1 first, then open a **new** PowerShell window:

```powershell
cd D:\d\verixa-final
$env:DATABASE_URL = "sqlite:///./demo.db"
$env:PUBLIC_URL = "http://localhost:8000"
$env:SECRET_KEY = "local-demo-only-secret-key-0123456789"
$env:WEBHOOK_SECRET = "local-demo-only-webhook-secret-0123456789"
.\.venv\Scripts\python.exe -m scripts.seed_demo
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000
```

Open <http://localhost:8000/login> and log in with `demo@verixa.dev` and the password `Verixa-Demo-2026`.

The sample pull requests and Test Library work here. **Analyse now** and **Link again** do not, because the demo has no
real GitHub sign in. Close this window when you finish, so its settings do not affect a normal run.

## Forgot password emails

The reset link is sent by email through Gmail. Add these to `.env` and restart the app, because `.env` is only read at start.
For Gmail, turn on 2-Step Verification, create an App Password, and use that instead of your normal password:

```text
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your-16-letter-app-password
MAIL_FROM=Verixa <you@gmail.com>
```

Without `SMTP_HOST`, no email is sent, and the reset link is printed in the app's window instead. That is only for trying it on
your own computer.

## Run the tests

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_validators tests.test_library tests.test_accounts tests.test_crud tests.test_twofactor tests.test_risk_rules tests.test_analysis_integration tests.test_qa_security tests.test_risk_eval tests.test_github_refresh tests.test_legal_pages tests.test_password_reset tests.test_live tests.test_ci_check tests.test_agent_fixes tests.test_manager_matching tests.test_agent_trace tests.test_agent_secrets tests.test_qa_units tests.test_qa_flow tests.test_qa_system
```

The tests use their own temporary database and take about 4 minutes. **Always name the modules. Never run
`unittest discover -s tests`**: it would skip the test database, so the app now refuses to start that way.

The browser tests (real browser, real app, a small staging app with bugs on purpose):

```powershell
cd tests\e2e; npx playwright test --project=qa --project=controlled --project=signup --project=forgot --project=profile; cd ..\..
``` For more cases to try by hand, see
[samples/test-data/README.md](samples/test-data/README.md).

## If something goes wrong

| What you see | What to do |
|---|---|
| `only one usage of each socket address` | The app is already running. Use that window, or close it and start again |
| `ERR_NGROK_334` or "endpoint is already online" | The ngrok address is running on another computer or window. Stop it there, then try again |
| `ngrok` is not recognized | Run it by its full path: `D:\d\copy\ngrok\ngrok.exe`. If that file is missing, unzip `ngrok-v3-stable-windows-amd64.zip` in the same folder |
| `ERR_NGROK_3200`, or the address says it is offline | Window 2 is closed. Start ngrok again |
| `ERR_NGROK_8012` | ngrok is on, but the app is not. Start Window 1 |
| `frontend/dist is missing` | Run `cd frontend; npm install; npm run build; cd ..` |
| `must be a long random string` | `SECRET_KEY` or `WEBHOOK_SECRET` is missing or too short in `.env` |
| GitHub says the redirect address is wrong | The callback in the GitHub app must match step 5 of first-time setup |
| "The saved sign in no longer works" | Press **Link again** and approve GitHub and Atlassian |
| A pull request does not appear by itself | Check that Window 2 is on, and that Integrations shows the webhook as verified. Use **Analyse now** meanwhile |
| Analysis says the Manager did not accept the output | The AI model failed or is over its limit. The rule-based label is still correct. Check the keys in `.env` |
| Run Now says "Add the staging address" | Enter the staging app's address on **Integrations**, step "Staging app" |
| A run fails with "Staging is not answering" | Start the staging app, or fix its address on Integrations |
| "Test tools are not installed" | Run `cd runner; npm install; npx playwright install chromium` |
| A ticket says "Jira refused" | Your Atlassian account needs permission to create issues in that Jira project |
| The page looks old | Run `npm run build` in `frontend`, restart the app, then press `Ctrl+F5` |
