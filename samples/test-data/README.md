# Test data: try to break Verixa yourself

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
