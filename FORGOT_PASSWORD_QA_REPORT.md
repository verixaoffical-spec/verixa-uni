# Forgot Password: QA Test Report

**Feature:** Forgot Password and Reset Password
**Run:** 2026-11-07 15:24 UTC, Playwright 1.64.1, Chromium
**Where:** the real Verixa app and agents on port 8011 with its own throwaway SQLite database (`tests/e2e/server.py`). Your real database in `.env` was never used.
**How to run again:** `cd tests/e2e` then `npx playwright test --project=forgot`, then `node fp_report.mjs`

Every status below comes from an actual run. A test is PASS only when Playwright checked the expected result.

## Summary

| Measure | Result |
|---|---|
| Test cases | 57 |
| Passed | 56 |
| Failed | 0 |
| Blocked | 1 |
| Not executed | 0 |
| Pass rate (of executed) | 100.0% |

## Critical and high severity defects

None found.

## 1. Navigation

| ID | Scenario | Steps | Expected | Actual | Status | Severity if failed |
|---|---|---|---|---|---|---|
| FP-NAV-01 | the login page shows a Forgot password link | Open /login → Find the Forgot password? link | The link is visible, enabled and points to /forgot-password | As expected | **PASS** | High |
| FP-NAV-02 | clicking it opens the Forgot Password page | Open /login → Click Forgot password? | The browser is on /forgot-password with the heading "Forgot your password?" | As expected | **PASS** | High |
| FP-NAV-03 | the page has an email field, a submit button and a way back, in that order | Open /forgot-password → Check each element | Email field, Send reset link button and Back to log in link are visible and enabled; field above button above link | As expected | **PASS** | Medium |
| FP-NAV-04 | Back to log in returns to the login page | Open /forgot-password → Click Back to log in | The browser is on /login | As expected | **PASS** | Medium |

## 2. Email validation

| ID | Scenario | Steps | Expected | Actual | Status | Severity if failed |
|---|---|---|---|---|---|---|
| FP-EM-01 | empty email is refused before anything is sent | Open /forgot-password → Enter "" → Click Send reset link | Message "Enter your email address", no request sent, page stays on the form | As expected | **PASS** | Medium |
| FP-EM-02 | no @ at all email is refused before anything is sent | Open /forgot-password → Enter "abc123" → Click Send reset link | Message "Enter a valid email address", no request sent, page stays on the form | As expected | **PASS** | Medium |
| FP-EM-03 | no domain ending email is refused before anything is sent | Open /forgot-password → Enter "user@gmail" → Click Send reset link | Message "Enter a valid email address", no request sent, page stays on the form | As expected | **PASS** | Medium |
| FP-EM-04 | no username email is refused before anything is sent | Open /forgot-password → Enter "@gmail.com" → Click Send reset link | Message "Enter a valid email address", no request sent, page stays on the form | As expected | **PASS** | Medium |
| FP-EM-05 | a registered email gets the confirmation and an email | Make an account → Ask for a link with its email | "Check your inbox" screen, one email in the inbox | As expected | **PASS** | Critical |
| FP-EM-06 | an unregistered email gets the same answer and no email | Ask for a link for an email with no account → Compare with a registered one | Same screen and same API answer as a registered email; no email sent | As expected | **PASS** | High |
| FP-EM-07 | spaces and capitals around the email are removed | Enter "  EMAIL  " with spaces and capitals | Accepted; the email goes to the trimmed, lowercase address | As expected | **PASS** | Medium |
| FP-EM-08 | an extremely long email is refused | Type a 300 character email → Send it straight to the API too | The field holds at most 254 characters; the page shows an error; the API answers 422 | As expected | **PASS** | Low |
| FP-EM-09 | an email with allowed special characters works | Make an account with qa.o'brien+reset_1@verixa.dev → Ask for a link | Accepted, and the email arrives | As expected | **PASS** | Low |
| FP-EM-10 | clicking Send many times quickly sends one request | Enter a registered email → Click Send reset link 5 times fast | One request and one email; the button is busy while sending | As expected | **PASS** | Medium |

## 3. Email delivery

| ID | Scenario | Steps | Expected | Actual | Status | Severity if failed |
|---|---|---|---|---|---|---|
| FP-MAIL-01 | the email has the right subject, greeting, link and expiry | Ask for a link → Open the test inbox | Subject "Reset your Verixa password", the account name, a /reset-password#token= link, "30 minutes", "works once" | As expected | **PASS** | High |
| FP-MAIL-02 | the link from the email opens the Reset Password page | Ask for a link → Open the link from the email | The "Choose a new password" form shows, with no error | As expected | **PASS** | Critical |
| FP-MAIL-03 | delivery to a real mailbox through SMTP | Set SMTP_HOST in .env → Ask for a link → Check a real mailbox | The email arrives in a real inbox | no mail server is set up (SMTP_HOST is empty in .env), so real delivery cannot be checked. The email content is checked through the test inbox instead (FP-MAIL-01). | **BLOCKED** | High |

## 4. Reset token

| ID | Scenario | Steps | Expected | Actual | Status | Severity if failed |
|---|---|---|---|---|---|---|
| FP-TOK-01 | a valid link is accepted | Open a fresh link → Set a new password | The password is changed | As expected | **PASS** | Critical |
| FP-TOK-02 | an expired link is refused by the server | Ask for a link → Move its expiry into the past (test database) → Open it and set a password | "not valid, or it has expired" message; password unchanged | As expected | **PASS** | Critical |
| FP-TOK-03 | a changed token is refused | Change one character of the token → Open it and set a password | Refused; password unchanged; the real link still works | As expected | **PASS** | Critical |
| FP-TOK-04 | the reset page without a token says the link is incomplete | Open /reset-password with no token | A clear message, a way to ask for a new link, and no password form | As expected | **PASS** | Medium |
| FP-TOK-05 | a used link cannot be used again | Reset the password with a link → Open the same link again | Second use refused; the first new password stays | As expected | **PASS** | Critical |
| FP-TOK-06 | asking twice: only the newest link works | Ask for a link twice → Try the first, then the second | First refused, second accepted; one link stored | As expected | **PASS** | High |
| FP-TOK-07 | refreshing the reset page | Open a link → Reload the page | No crash. The token was removed from the address bar on first load, so after a reload the page says the link is incomplete and offers a new one | As expected | **PASS** | Low |
| FP-TOK-08 | Back and Forward after a reset do not reopen the form | Open /login, then the link → Reset the password → Press Back, then Forward | Back shows the login page; Forward shows the reset page without a usable form | As expected | **PASS** | Medium |

## 5. New password

| ID | Scenario | Steps | Expected | Actual | Status | Severity if failed |
|---|---|---|---|---|---|---|
| FP-PW-01 | empty password is refused on the page | Enter "" twice → Click Save new password | Message containing "Enter a password"; nothing sent; password unchanged | As expected | **PASS** | High |
| FP-PW-02 | common, weak password is refused on the page | Enter "password123" twice → Click Save new password | Message containing "too common"; nothing sent; password unchanged | As expected | **PASS** | High |
| FP-PW-03 | below the minimum length of 8 password is refused on the page | Enter "ab1cd" twice → Click Save new password | Message containing "Use at least 8 characters"; nothing sent; password unchanged | As expected | **PASS** | High |
| FP-PW-04 | a password of exactly 8 characters is accepted | Enter "kq7mz2xp" (8 characters) twice → Save | Accepted; logging in with it works | As expected | **PASS** | Medium |
| FP-PW-05 | a password over 128 characters is refused | Type 140 characters in the field → Send 129 characters straight to the API | The field keeps at most 128; the API answers 422; password unchanged | As expected | **PASS** | Low |
| FP-PW-06 | different passwords in the two fields are refused | Enter two different valid passwords → Save | "The two passwords do not match"; nothing sent | As expected | **PASS** | High |
| FP-PW-07 | matching valid passwords are accepted | Enter the same strong password twice → Save | "Password changed" screen | As expected | **PASS** | Critical |
| FP-PW-08 | Show password reveals and hides the new password | Type a password → Click Show password, then Hide password | The field switches between hidden and visible | As expected | **PASS** | Low |
| FP-PW-09 | the same control reveals the confirm field | Type in Type it again → Click Show password | The confirm field becomes visible too, so both can be compared | As expected | **PASS** | Low |
| FP-PW-10 | a password with special characters works | Set "Qa!@#$%^&*()_+-=[]{};:,.<>/?9 ü" as the password → Log in with it | Accepted, and logging in with exactly that text works | As expected | **PASS** | Medium |
| FP-PW-11 | a password containing the account name is refused by the server | Enter "ResetTester2026" (contains the name "Reset Tester") → Save | The server refuses it and the page shows "Do not use your name"; the link still works | As expected | **PASS** | Medium |

## 6. End to end

| ID | Scenario | Steps | Expected | Actual | Status | Severity if failed |
|---|---|---|---|---|---|---|
| FP-E2E-01 | the whole journey, proved by logging in | Log in page → Forgot password? → Send link → Open the email link → Set a new password → Log in with the new password → Log out, log in with the old password → Open the link again | New password logs in to the dashboard; old password is refused; the link is refused the second time | As expected | **PASS** | Critical |

## 7. Security

| ID | Scenario | Steps | Expected | Actual | Status | Severity if failed |
|---|---|---|---|---|---|---|
| FP-SEC-01 | SQL injection in the email field is refused and changes nothing | Enter ' OR '1'='1 and admin'-- in the email field | Refused as an invalid email; no email sent; no reset row created | As expected | **PASS** | Critical |
| FP-SEC-02 | SQL injection in the password field is stored as plain text, safely | Set the new password to x' OR '1'='1' --9 → Log in with it; check another account | Saved as an ordinary password: logging in needs exactly that text; another account is untouched | As expected | **PASS** | Critical |
| FP-SEC-03 | script in the fields never runs | Enter <script>alert(1)</script> in the email field → Enter <img src=x onerror=alert(1)>9a as a new password | No alert appears; the email is refused; the password is stored as text | As expected | **PASS** | Critical |
| FP-SEC-04 | guessing tokens is slowed down | Send 20 made-up tokens from one address → Send one more | All refused with 400, then 429 with Retry-After | As expected | **PASS** | High |
| FP-SEC-05 | a link only ever changes its own account's password | Get a link for account A → Use it while naming account B's email → Check B | Only A changes; there is no way to name another account; B logs in with its old password | As expected | **PASS** | Critical |
| FP-SEC-06 | repeated requests for one email are limited | Ask for a link for one email 4 times in an hour | The first 3 send an email; the 4th is refused with 429 and the page shows a countdown | As expected | **PASS** | High |
| FP-SEC-07 | the token is not sent to the server log or kept in the address bar | Open a reset link → Watch every request the page makes → Read the address bar and history | The token never appears in a request URL or a Referer, and is removed from the address bar on load | As expected | **PASS** | High |
| FP-SEC-08 | reset links use the public address, which is HTTPS for the real site | Read the link in the email → Read the scheme of PUBLIC_URL in the real .env (only the scheme) | The link is built from PUBLIC_URL; the real site uses https:// | As expected | **PASS** | Medium |
| FP-SEC-09 | forms posted from another website are refused | POST /auth/forgot and /auth/reset with Origin https://evil.example | Both refused with 403; no email sent; password unchanged | As expected | **PASS** | High |
| FP-SEC-10 | a reset signs out every other session | Log in on browser A → Reset the password on browser B → Use browser A again | Browser A is signed out and sent to the login page | As expected | **PASS** | Critical |
| FP-SEC-11 | reset pages and answers are never cached | Load /forgot-password and /reset-password → Send a bad reset | Cache-Control: no-store on the pages and on the refusal | As expected | **PASS** | Low |

## 8. Database

| ID | Scenario | Steps | Expected | Actual | Status | Severity if failed |
|---|---|---|---|---|---|---|
| FP-DB-01 | a request stores one link, as a hash only | Ask for a link → Read the password_resets table | One row for the account; it holds the SHA-256 of the token, never the token | As expected | **PASS** | Critical |
| FP-DB-02 | the link expires 30 minutes after it is made | Ask for a link → Read its expiry | expires_at is 30 minutes after created_at, and about 30 minutes from now | As expected | **PASS** | High |
| FP-DB-03 | a used link is deleted | Reset the password → Read the table | No link left for the account | As expected | **PASS** | Critical |
| FP-DB-04 | the password hash changes after a reset, and stays scrypt | Fingerprint the hash → Reset → Fingerprint again | Different fingerprint; still an scrypt hash; the session version goes up | As expected | **PASS** | Critical |
| FP-DB-05 | the new password is never stored as plain text | Reset to a known password → Search the user row for it | The password text is nowhere in the row | As expected | **PASS** | Critical |
| FP-DB-06 | a refused new password changes nothing | Send a weak password with a valid link | Hash, session version and the link all unchanged | As expected | **PASS** | High |
| FP-DB-07 | a bad token changes no account | Send a made-up token | No user row changes; no link is removed | As expected | **PASS** | High |
| FP-DB-08 | many requests leave exactly one link | Ask for a link 3 times | Exactly one row for the account, matching the newest email | As expected | **PASS** | High |
| FP-DB-09 | only the intended account is updated | Make accounts A and B, both with links → Reset A's password | A changes; B's hash, session version and link are untouched | As expected | **PASS** | Critical |

## Items from the test list that were removed or changed

The list in `tests.txt` is general. These items did not fit Verixa, so they were removed or adapted:

| Item in the list | Decision | Why |
|---|---|---|
| 8.10 Security audit logs are generated | Removed | Verixa has no audit log feature, and neither the SRS nor the proposal asks for one. The server's request log is not an audit log, so testing for one would only report a missing feature that was never planned |
| 1.6 Elements are "correctly positioned" | Narrowed | No layout is specified, so FP-NAV-03 checks the order that matters: email field, then button, then the way back |
| 3.3 to 3.4 Access the test inbox | Adapted | No mail server is set up, so the test copy of the app writes each email to a test inbox file instead. Content and links are checked from there (FP-MAIL-01, FP-MAIL-02). Delivery to a real mailbox is reported as BLOCKED (FP-MAIL-03) |
| 5.9 Confirm Password visibility | Adapted | Verixa uses one Show password button for both fields. FP-PW-09 checks that it reveals the confirm field too |
| 7.8 HTTPS in production | Adapted | Links are built from `PUBLIC_URL`. FP-SEC-08 checks the link uses it, and reads only the scheme of `PUBLIC_URL` in your real `.env` |
| 8.1 to 8.9 SQL checks | Adapted | Run read-only on the tests' own SQLite file through `tests/e2e/db_check.py`, which prints only yes/no answers and short fingerprints, never a hash or a token. Your Neon database was not touched |
| 8.3 Tokens marked consumed | Adapted | Verixa deletes a link once used, rather than marking it. FP-DB-03 checks the row is gone |

Added because they matter for Verixa: FP-PW-11 (the server refuses a password containing the account's name, which the page cannot know), FP-SEC-04 (guessing tokens is slowed down) and FP-SEC-11 (reset pages are never cached).

## SQL and database findings

- A request stores exactly one link per account. Asking again replaces it, so there are never two live links (FP-TOK-06, FP-DB-08).
- Only the SHA-256 of the token is stored, never the token itself (FP-DB-01).
- Links expire 30 minutes after they are made, and the server enforces it (FP-DB-02, FP-TOK-02).
- A used link is deleted, and the password hash changes and stays scrypt (FP-DB-03, FP-DB-04).
- The new password never appears in plain text (FP-DB-05).
- Refused passwords and made-up tokens change nothing (FP-DB-06, FP-DB-07). Only the intended account changes (FP-DB-09, FP-SEC-05).

## Security findings

No vulnerability was found. What was checked:

- SQL injection in the email and password fields is refused or stored as ordinary text, and nothing else changes (FP-SEC-01, FP-SEC-02).
- Script in either field never runs (FP-SEC-03).
- Tokens cannot be changed, reused or guessed: guesses are cut off after 20 from one address (FP-TOK-03, FP-TOK-05, FP-SEC-04).
- A link changes only its own account. There is no way to name another account (FP-SEC-05).
- Asking for links is limited to 3 per email per hour, and the page shows a countdown (FP-SEC-06).
- The token is never sent to the server in a URL or Referer, so it cannot reach server or tunnel logs, and it is removed from the address bar on load (FP-SEC-07).
- Requests from another website are refused (FP-SEC-09).
- A reset signs out every other session (FP-SEC-10).
- Reset pages and answers are never cached (FP-SEC-11).

## Observations (not defects)

- **Refreshing the reset page** (FP-TOK-07): the token is removed from the address bar on first load, for safety, so a refresh shows "This reset link is not complete". Opening the link from the email again works. This trades a little convenience for not leaving the token in history.
- **Rate limits are kept in memory**: they reset when the server restarts. Fine for one server, but they would need a shared store if Verixa ever runs on several.
- **Real email delivery is untested** until a mail server is set in `.env` (FP-MAIL-03).

## Overall assessment

The Forgot Password feature works end to end: a person can ask for a link, open it from the email, set a new password, and log in with it, while the old password and the used link stop working. The backend enforces every rule the page shows, the database keeps only hashed tokens with a 30 minute expiry, and the security checks found no way to reset another account, reuse a link or leak the token. The one gap is real email delivery, which needs SMTP settings before it can be tested.
