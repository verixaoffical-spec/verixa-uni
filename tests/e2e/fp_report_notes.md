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
