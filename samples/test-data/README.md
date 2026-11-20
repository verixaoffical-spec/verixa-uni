# Test data: try to break Verixa yourself

> **This branch is `verixa-fyp1`: FYP I only (UC1 to UC7).** The four FYP II features (QA Memory, Suggest a Fix,
> Regression Comparison and Risk Trends, UC8 to UC11) are not in this branch. They are added on top of it in the
> branch `verixa-fyp2`. Where this file mentions them, it describes `verixa-fyp2`.

## 1. Start a private copy

Run these in PowerShell from the project folder. They use a throwaway SQLite file and fake secrets, so your real
database is never touched, even if you have a `.env`.

```powershell
$env:DATABASE_URL = "sqlite:///./demo.db"
$env:PUBLIC_URL = "http://localhost:8000"
$env:SECRET_KEY = "local-demo-only-secret-key-0123456789"
$env:WEBHOOK_SECRET = "local-demo-only-webhook-secret-0123456789"
$env:GITHUB_CLIENT_ID = "x"; $env:GITHUB_CLIENT_SECRET = "x"
$env:ATLASSIAN_CLIENT_ID = "x"; $env:ATLASSIAN_CLIENT_SECRET = "x"

.\.venv\Scripts\python.exe -m scripts.seed_demo
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000
```

Open <http://localhost:8000/login>. Run `seed_demo` again at any time to reset everything.

| Account | Password | Has |
|---|---|---|
| `demo@verixa.dev` | `Verixa-Demo-2026` | Repository `demo/shop` and 6 pull requests, one with a hostile title |
| `other@verixa.dev` | `Verixa-Demo-2026` | Repository `other/shop`, empty. Use it to check that accounts stay separate |

**Expected in this demo:** the message *"the saved sign in no longer works ... Link again"*, because the demo GitHub token
is fake. It shows how a revoked token is handled. Do not press **Link again** in the demo: it opens GitHub, which
refuses the fake app, and the account then loses its fake link until you run `seed_demo` again.
**Analyse now** also fails here with a clear message, because it needs a real GitHub token.

## 2. Sign up at `/signup`: every row must be refused

Use a valid value for the other fields: name `Test User`, email `new.user@example.com`, password `Blue-Harbor-47`.

| Field | Try this | Expected message |
|---|---|---|
| Name | `<script>alert(1)</script>` | Use letters, spaces and simple punctuation only |
| Name | `javascript:alert(1)` | same |
| Name | `" onmouseover="alert(1)` | same |
| Name | `'; DROP TABLE users;--` | same |
| Name | `12345` or `!!!!!` | same |
| Name | `{{7*7}}` or `${alert(1)}` | same |
| Name | `x` | Use at least 2 characters |
| Email | `<script>alert(1)</script>@evil.com` | Enter a valid email address |
| Email | `"><img src=x onerror=alert(1)>@x.com` | same |
| Email | `javascript:alert(1)@x.com` | same |
| Email | `a;b@x.com` or `.a@b.com` or `a.@b.com` | same |
| Email | `a@b` or `a@b.c0m` or `a@-b.com` | same |
| Email | `demo@verixa.dev` | An account with this email already exists |
| Password | `short1` | Use at least 8 characters |
| Password | `abcdefgh` or `12345678` | Use at least one letter and one number |
| Password | `password123` or `aaaaaaa1` or `a1a1a1a1` | That password is too common |
| Password | `testuser99` with the name `Test User` | Do not use your name in the password |
| Password | `newuser123x` with the email `new.user@...`: *accepted*, but `new.user1x` is refused | Do not use your email address |

These must be **accepted**: `Zoë O'Brien-Smith`, `李小龙`, `José María`, `Martin Luther King Jr.` as names, and
`first.last+tag@sub.company.co.uk` as an email.

## 3. Log in at `/login`

| Try this | Expected |
|---|---|
| `demo@verixa.dev` with the right password | Dashboard opens |
| `DEMO@Verixa.dev` with the right password | Dashboard opens: email case does not matter |
| Wrong password | "Email or password is incorrect", the same as for an unknown email |
| Wrong password 5 times | Locked with a countdown |
| `' OR '1'='1` as the email | "Enter a valid email address" |

## 4. Addresses to paste in the browser

Each should stay on Verixa and never show the text or run the script.

| Address | Expected |
|---|---|
| `/login?error=Your account is hacked, call 555-0100` | Banner says only "Sign in could not be completed" |
| `/login?error=<img src=x onerror=alert(1)>` | Same banner, no alert |
| `/login?next=https://evil.example` then log in | You land on the dashboard |
| `/login?next=//evil.example` then log in | You land on the dashboard |
| `/login?next=javascript:alert(1)` then log in | You land on the dashboard, no alert |
| `/.env`, `/.git/config`, `/backend/main.py` | Not Found |
| `/verixa_prototype.html` while logged out | Goes to log in |

## 5. Test Library uploads

Log in as `demo@verixa.dev`, open the Test Library (flask icon), and upload the files in this folder.

**`should-pass/`: all accepted. Press Confirm import, then reload to see that they were saved.**

| File | Why it matters |
|---|---|
| `login.spec.ts` | Holds `/Bob's [(]shop/` and `page.$eval`, both of which look broken or dangerous but are fine |
| `script-in-title.spec.ts` | The test title is `<img src=x onerror=alert(1)>`. It must show as text, with no alert |
| `shop.postman_collection.json` | Holds `{{base url}}`, `localhost` and a space in the query |

**`should-fail/`: all refused, each with its reason shown on a red card.**

| File | Expected reason |
|---|---|
| `uses-eval.spec.ts` | Uses eval, which is not allowed |
| `uses-new-function.spec.ts` | Uses new Function, which is not allowed |
| `uses-child-process.spec.ts` | Uses child_process, which is not allowed |
| `broken-bracket.spec.ts` | A bracket or quote is not closed |
| `no-tests.spec.ts` | No tests found |
| `html-page.spec.ts` | Missing import from '@playwright/test' |
| `random-garbage.spec.ts` | Missing import from '@playwright/test' |
| `empty.spec.ts` | File is empty |
| `javascript-file.spec.js` | JavaScript specs are not accepted |
| `..spec.ts` | File name needs a name before .spec.ts |
| `collection-javascript-url.json` | Uses a javascript address, which is not allowed |
| `collection-file-url.json` | Uses a file address, which is not allowed |
| `collection-data-url.json` | Uses a data address, which is not allowed |
| `collection-not-a-url.json` | Has an address that is not a URL |
| `collection-bad-method.json` | Uses unsupported method HACK |
| `collection-no-requests.json` | Collection has no requests |
| `collection-not-json.json` | Not valid JSON |
| `collection-is-a-list.json` | Expected a Postman collection object |
| `collection-environment-file.json` | This is a Postman environment file |

Upload specs in the **Playwright specs** tab and `collection-*` files in the **Postman collection** tab.

## 6. Risk Analysis (top icon in the left rail)

| Check | Expected |
|---|---|
| Tiles | 6 pull requests, High 3, Medium 1, Low 1 |
| Pull request #6 | The title shows the literal text `<img src=x onerror=alert('xss')>`, with no alert and no broken image |
| Click #1 | Why this label, reasoning, test areas and an Open on GitHub link |
| Click #4 and #5 | Needs review and Failed, each with its reason |
| Press Tab to a row, then Enter | The row opens from the keyboard |
| Letters in the PR # box | Cannot be typed |

## 7. One account cannot reach another

1. As `demo@verixa.dev`, note that `/api/analysis/pull-requests/1` shows data.
2. Log out and log in as `other@verixa.dev`, then open the same address. It must answer **404**.
3. The Test Library and Risk Analysis of this account must be empty.

## 8. Direct API attacks (PowerShell, server running)

Each line prints the status it should get.

```powershell
function Try-It($path, $body) { try { (Invoke-WebRequest "http://localhost:8000$path" -Method Post -Body $body -ContentType "application/json" -UseBasicParsing).StatusCode } catch { [int]$_.Exception.Response.StatusCode } }

Try-It "/auth/login"  '{"email":"a@b.co","password":"\ud800"}'     # 422, it used to crash with 500
Try-It "/auth/signup" '{"name":"<b>x</b>","email":"a@b.co","password":"Blue-Harbor-47"}'   # 422
Try-It "/auth/signup" '[]'                                          # 422
Try-It "/auth/signup" 'this is not json'                            # 422
Try-It "/webhooks/github" '{}'                                      # 401, no signature
Try-It "/api/library/apply" '{}'                                    # 401, not logged in
Try-It "/api/analysis/analyse" '{"pr_number":4}'                    # 401, not logged in
```

## 9. Run the automated tests

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_validators tests.test_library tests.test_accounts tests.test_crud tests.test_twofactor tests.test_risk_rules tests.test_analysis_integration tests.test_qa_security
```

## 10. Staging address, Run Now, tickets and trends (UC4 to UC11)

**Staging address** (Integrations, step "Staging app"). Every row except the last must be refused.

| Try this | Expected message |
|---|---|
| (empty) | Enter the staging address |
| `ftp://files.example.com` or `javascript:alert(1)` | Use an http:// or https:// address |
| `http://169.254.169.254/latest/meta-data` | That address is not allowed |
| `http://[::ffff:169.254.169.254]/` | That address is not allowed |
| `http://user:secret@staging.example.com` | Leave the user name and password out of the address |
| `http://staging.example.com/?debug=1` | Leave ? and # parts out of the address |
| `http://localhost:8000` (Verixa's own address) | That is the Verixa server itself |
| `http://no-such-host.invalid` | could not be found. Check the address |
| The real address of your staging app | Saved, with the status code it answered |

**Run Now** (Risk Analysis). Upload `shoplite/shoplite-cart.spec.ts` and `shoplite/shoplite.postman_collection.json` first.

| Do this | Expected |
|---|---|
| Press Run Now with no staging address saved | A message with an **Open Integrations** button |
| Press Run Now on a High risk pull request | The run opens with live progress, then sorted results |
| Press Run Now again while it is running | "already in progress" |
| Stop the staging app, then press Run Now | "Staging ... is not answering" |
| A spec whose page answers 404 on staging | Marked **deployment pending**, never failed |

**Ticket draft** (Test Runs, a real bug). Each of the first four must be refused; nothing reaches Jira until you approve.

| Try this | Expected |
|---|---|
| Title `abc` | Refused: too short |
| Remove every step | Refused |
| More than 20 steps | Refused |
| Title `Cart <img src=x onerror=alert(1)> total` | Saved and shown as plain text, with no alert |

**Addresses to paste while logged in**

| Address | Expected |
|---|---|
| `/api/trends?days=30` | Data |
| `/api/trends?days=5` or `/api/trends?days=abc` | 422: only 7, 30, 90 and 365 are offered |
| `/api/evidence/0` | 422 |
| `/api/evidence/..%2F..%2F.env` | 404 |
| `/api/runs/1` as `other@verixa.dev` | 404: a run of another account cannot be seen |

**Risk label marked wrong** (Risk Analysis, open a scored pull request, "Label wrong? I expected…")

| Do this | Expected |
|---|---|
| Pick a label other than the one shown | "Saved to QA Memory". The label itself does not change |
| Open QA Memory | A new entry "Risk label ... was marked wrong" |
| Open a later pull request in the same module | The entry is listed under "QA Memory used" |
| Send the same label it already has, or mark it twice (API) | 422, then 409 |

All of these, 68 inputs in total, are also run automatically:

```powershell
cd tests\e2e; npx playwright test --project=inputs
```

The table of every input and its result is written to `tests/e2e/test-results/inputs.md`.

## 11. The demo with the TaskFlow staging site

`staging/server.py` is TaskFlow, a small ordinary website: a home page, pricing, a contact form, a sign in, a task
dashboard and an API. It is not a shop. Verixa tests any website, and this one only gives it something to find.
It needs only Python.

```powershell
python staging\server.py          # the site:     http://127.0.0.1:4000
                                  # the switches: http://127.0.0.1:4000/demo
```

**Set up once**

1. In Verixa, open **Integrations** and save the staging address `http://127.0.0.1:4000`.
2. Open the **Test Library**. If the demo's own files are there, delete them. Upload from `samples/test-data/demo-site/`:
   `taskflow.spec.ts` and `taskflow-docs.spec.ts`, and on the Postman tab `taskflow.postman_collection.json`.
3. Press **Confirm import**.

**The demo, one Run Now per row** (use a High risk pull request so every test runs)

| On `/demo` | Press Run Now, then show | Why it matters |
|---|---|---|
| Everything off | 14 passed, 1 deployment pending (the Docs page test) | A page that is not on staging yet is not called a bug |
| **Pricing bug** on | 2 real bugs: the pricing screen test (yearly Pro shows $120, expected $96) and the API test "List plans" | The same fault is caught from the screen and from the API |
| **Contact bug** on | 2 real bugs: the contact form screen test and the API request "Contact message is accepted" (answered 500) | A server error has proof: screenshot, logs, status |
| **Tasks bug** on | 2 real bugs: "a signed in user can add a task..." and "The task is in the list" | A fault that answers 201 but loses the data |
| **Docs page is deployed** on | The Docs test now runs and passes | Deployment pending goes away once the page exists |

Then approve a ticket draft. In version 2 also press **Suggest a fix**, switch the bug off, run again and open
**Compare runs** to see "fixed".

**Inputs to try on the site itself**

| Input | Expected |
|---|---|
| Sign in with `demo@taskflow.test` / `Taskflow123!` | The task dashboard opens |
| Sign in with `demo@taskflow.test` / `Wrong-password-1` | "Email or password is incorrect" |
| Contact form with every field empty | "Please fill in every field" |
| Contact form with a name, an email and a message | "Thanks, we got your message" |
| `http://127.0.0.1:4000/docs` while the Docs switch is off | 404 |
| `http://127.0.0.1:4000/no-such-page` | "Page not found" |

This demo is checked automatically by `python -m unittest tests.test_staging_demo`, with real Playwright and Newman.

## 12. Testing a live website (FYP Forge)

Verixa runs against any website that has an http or https address, so it can also test a site that is already live.
Your own website is `https://fypmate-ai.lovable.app` (FYP Forge). The files in `samples/test-data/fyp-forge/` were
written from what that site really shows today.

**Keep a live run read only.** The SRS says tests run on staging and never on the live system (BR8), but Verixa cannot
tell whether an address is live, so the tester has to choose safe tests. These files only look and click. They never
create an account, never sign in with a real one, and never send, buy or delete anything. The one sign in attempt uses
the made up address `verixa.check@example.invalid` and is refused.

1. In **Integrations** save the staging address `https://fypmate-ai.lovable.app`.
2. In the **Test Library** upload `fyp-forge.spec.ts` and, on the Postman tab, `fyp-forge.postman_collection.json`.
3. Press **Run Now** on any scored pull request.

| Test | What it checks |
|---|---|
| The home page sends a visitor to the sign in page | `/` goes to `/auth`, the title has "FYP Forge", the heading is "Welcome Back" |
| The sign in form has an email and a password field | Both fields are there |
| An empty form says what is required | "Email is required" and "Password is required" |
| A wrong password is refused | "Invalid email or password", the visitor stays on `/auth` |
| The Sign Up tab shows the account form | "Create Your Account" |
| The page fits a phone | No sideways scrolling at 390 px |
| The page loads without a console error | No page error, no console error |
| API requests | `/`, `/auth`, `/robots.txt` and `/sitemap.xml` answer 200 with the right type, and the home page answers in under 3 seconds |

**A limit to know about.** FYP Forge is a single page app: every address, even one that does not exist, answers 200 with
the same page. Verixa marks a test "deployment pending" when a page answers 404, so on a site like this a missing page
shows as a failed test, not as pending.
