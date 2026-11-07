"""Rule based risk scoring. Pure functions, no network, easy to test and tune.

score  = size points + defect history points + sensitive area points
label  = Low (<=3), Medium (4-6), High (>=7), then raised by minimum labels:
         sensitive security/payment code -> at least High, sensitive data/config code -> at least Medium,
         a very large change -> High."""
import os
import re

HIGH_WORDS = {"auth", "authn", "authz", "authentication", "authorization", "login", "logout", "signin",
              "signup", "token", "jwt", "session", "password", "passwd", "credential", "oauth",
              "permission", "rbac", "secret", "encrypt", "crypto", "payment", "checkout", "billing",
              "charge", "refund", "invoice", "coupon", "discount", "price", "pricing", "stripe",
              "paypal", "wallet", "security"}
MEDIUM_WORDS = {"user", "account", "profile", "cart", "order", "inventory", "email", "upload",
                "notification", "admin", "config", "migration", "schema", "database", "db"}
WRAPPER_DIRS = {"src", "app", "apps", "lib", "packages"}
MODULE_DIRS = {"modules", "module"}  # src/modules/auth is the auth module, not one module called "modules"
RANK = {"Low": 0, "Medium": 1, "High": 2}
LABELS = ["Low", "Medium", "High"]


def _extra(env: str) -> set[str]:
    return {w.strip().lower() for w in os.getenv(env, "").split(",") if w.strip()}


def _norm(t: str) -> str:
    return t[:-1] if len(t) > 3 and t.endswith("s") and not t.endswith("ss") else t


def tokens(text: str) -> set[str]:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text).lower()
    return {_norm(t) for t in re.split(r"[^a-z0-9]+", text) if t}


def is_test_or_doc(path: str) -> bool:
    p = path.lower()
    return (any(seg in p.split("/") for seg in ("test", "tests", "__tests__", "docs", "doc"))
            or ".spec." in p or ".test." in p or p.endswith((".md", ".txt", ".rst")))


def module_of(path: str) -> tuple[str, str]:
    """src/payments/tax.py -> ("payments", "src/payments"), README.md -> ("root", "")"""
    parts = path.split("/")
    if len(parts) == 1:
        return "root", ""
    at = 1 if parts[0] in WRAPPER_DIRS and len(parts) > 2 else 0
    if parts[at] in MODULE_DIRS and len(parts) > at + 2:
        at += 1
    return parts[at], "/".join(parts[:at + 1])


def size_points(files: int, lines: int) -> int:
    f = 3 if files >= 10 else 2 if files >= 4 else 1
    l = 3 if lines >= 500 else 2 if lines >= 100 else 1
    return f + l


def defect_points(defects: int) -> int:
    # capped at 3: a module with 20 defects is treated the same as 10
    return 0 if defects <= 0 else 3 if defects >= 10 else 2 if defects >= 4 else 1


def sensitivity(files: list[dict]) -> dict:
    """Looks at changed file paths, and at the changed lines for security or payment words.
    Test and doc files are ignored. Returns {"level": high|medium|none, "reasons": [...]}."""
    high_w, med_w = HIGH_WORDS | _extra("HIGH_RISK_KEYWORDS"), MEDIUM_WORDS | _extra("MEDIUM_RISK_KEYWORDS")
    high, medium = [], []
    for f in files:
        path = f["filename"]
        if is_test_or_doc(path):
            continue
        toks = tokens(path)
        if toks & high_w:
            high.append(f"{path} ({', '.join(sorted(toks & high_w))})")
            continue
        changed = " ".join(l[1:] for l in (f.get("patch") or "").splitlines()
                           if l[:1] in "+-" and not l.startswith(("+++", "---")))
        hits = tokens(changed) & high_w
        if len(hits) >= 2:                      # two different sensitive words in the changed code
            high.append(f"{path} (code mentions {', '.join(sorted(hits)[:4])})")
        elif toks & med_w:
            medium.append(f"{path} ({', '.join(sorted(toks & med_w))})")
    if high:
        return {"level": "high", "reasons": high[:3]}
    if medium:
        return {"level": "medium", "reasons": medium[:3]}
    return {"level": "none", "reasons": []}


# Removed lines that protect the app. Deleting one is riskier than adding code, however small the change,
# so each gives a minimum label. Patterns are matched on the removed ("-") lines of code files only.
REMOVALS = [
    ("High", "a login or permission check", re.compile(
        r"\b(?:is_?authenticated|is_?auth\w*|require_?(?:auth|login|user|admin|role|permission)\w*|login_required|"
        r"is_?admin|is_?owner|has_?(?:role|permission|access)\w*|check_?(?:auth|permission|access)\w*|can_?(?:access|edit|delete)\w*|"
        r"authori[sz]e\w*|verify_?(?:token|jwt|session|signature)\w*|jwt\.verify|ensure_?(?:auth|logged)\w*)\b"
        r"|\bstatus\(\s*40[13]\s*\)|\babort\(\s*40[13]\b|\bHTTP_40[13]|\b(?:raise|throw)\s+\w*(?:Unauthori[sz]ed|Forbidden|PermissionDenied)",
        re.I)),
    ("High", "a security setting", re.compile(
        r"\b(?:csrf\w*|helmet|cors\(|rate_?limit\w*|limiter|secure\s*[:=]\s*true|httponly|samesite|"
        r"content[-_]security[-_]policy|strict[-_]transport|verify\s*[:=]\s*(?:true|1)|ssl_?verify)\b", re.I)),
    ("Medium", "input checking", re.compile(
        r"\b(?:validate\w*|sanitiz\w*|escape\w*|is_?valid\w*|assert\w*|schema\.parse|\.safeParse)\b", re.I)),
    ("Medium", "error handling", re.compile(r"^\s*(?:try\s*[:{]|catch\b|except\b|\}\s*catch\b|finally\b|raise\b|throw\b)", re.I)),
]
TEST_CASE = re.compile(r"^\s*(?:(?:it|test|describe)(?:\.\w+)?\s*\(|def\s+test_|async\s+def\s+test_)")


def risky_removals(files: list[dict]) -> list[tuple[str, str]]:
    """(minimum label, reason) for each kind of protective line this change deletes, at most one per kind."""
    found: dict[str, tuple[str, str]] = {}
    for f in files:
        path, patch = f["filename"], f.get("patch") or ""
        removed = [line[1:] for line in patch.splitlines() if line.startswith("-") and not line.startswith("---")]
        added_lines = [line[1:] for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++")]
        added = " ".join(added_lines)
        if not removed:
            continue
        if is_test_or_doc(path):
            gone = [line for line in removed if TEST_CASE.search(line)]
            if gone and len(gone) > len([line for line in added_lines if TEST_CASE.search(line)]):
                found.setdefault("tests", ("Medium", f"removed {len(gone)} test case(s) in {path}"))
            continue
        for label, what, pattern in REMOVALS:
            for line in removed:
                m = pattern.search(line)
                # Moved, not removed: the same check still appears in the added lines
                if m and m.group(0).strip().lower() not in added.lower():
                    found.setdefault(what, (label, f"removed {what} in {path}: {line.strip()[:80]}"))
                    break
    return list(found.values())


def ci_factor(ci: dict | None) -> str | None:
    """One line for the factor trace about the commit's CI, or None when CI was not checked."""
    if not ci:
        return None
    state = ci.get("state")
    if state == "failure":
        return f"ci: failing on this commit - {', '.join(ci.get('failed') or ['a check'])}"
    if state == "pending":
        return "ci: still running when scored. A failure later raises the label to High"
    if state == "success":
        return f"ci: all {ci.get('passed', 0)} check(s) passed"
    if state == "none":
        return "ci: no checks run on this commit"
    return "ci: could not be read, so a broken build would not show here"


def assess(files: list[dict], defects: int, defect_note: str = "", history_known: bool = True, total_files: int | None = None,
           ci: dict | None = None, secrets_added: int = 0) -> dict:
    """history_known=False: every defect lookup failed, which says nothing about the module's history.
    total_files: how many files the pull request really has, when GitHub would not list them all.
    ci: the commit's CI result from github_client.ci_status. A failing build or test run means the change
    breaks something, whatever it looks like, so it raises the label to High.
    secrets_added: values that look like a key or password in the added lines (agents/redact.py). A secret
    written into the code leaks to everyone who can read the repository, so it raises the label to High."""
    lines = sum(f["additions"] + f["deletions"] for f in files)
    size = size_points(len(files), lines)
    d_pts = defect_points(defects)
    sens = sensitivity(files)
    s_pts = {"high": 2, "medium": 1, "none": 0}[sens["level"]]
    score = size + d_pts + s_pts
    base = "Low" if score <= 3 else "Medium" if score <= 6 else "High"

    floors = []
    if sens["level"] == "high":
        floors.append(("High", "sensitive security or payment code is touched"))
    elif sens["level"] == "medium":
        floors.append(("Medium", "user, data or config code is touched"))
    if size >= 6:
        floors.append(("High", "very large change (10+ files and 500+ lines)"))
    if ci and ci.get("state") == "failure":
        floors.append(("High", "the build or tests fail on this commit"))
    removals = risky_removals(files)
    for minimum, why in removals:
        floors.append((minimum, why))
    if secrets_added:
        floors.append(("High", "a secret is written into the code"))
    label, reason = base, None
    for fl, why in floors:
        if RANK[fl] > RANK[label]:
            label, reason = fl, why

    factors = [f"size: {len(files)} file(s), {lines} lines changed ({size} pts)"]
    if total_files and total_files > len(files):
        factors.append(f"incomplete: only {len(files)} of {total_files} changed files could be read, "
                       "so the real risk may be higher")
    note = f" ({defect_note})" if defect_note else ""
    if not history_known:
        factors.append(f"defect history: unknown, counted as 0 pts, so the real risk may be higher{note}")
    elif defects:
        factors.append(f"defect history: {defects} past fix(es) in this module ({d_pts} pts){note}")
    else:
        factors.append(f"defect history: none found{note}")
    factors.append(f"sensitive area: {sens['level']}" + (f" - {'; '.join(sens['reasons'])}" if sens["reasons"] else "")
                   + f" ({s_pts} pts)")
    for _, why in removals:
        factors.append(f"removal: {why}")
    if secrets_added:
        factors.append(f"secret in code: {secrets_added} value(s) that look like a key or password were added")
    if line := ci_factor(ci):
        factors.append(line)
    factors.append(f"score {score} gives {base}" + (f", raised to {label}: {reason}" if reason else ""))
    return {"score": score, "base_label": base, "risk_label": label, "risk_factors": factors,
            "size_points": size, "defect_points": d_pts, "sensitivity": sens["level"],
            "lines_changed": lines}
