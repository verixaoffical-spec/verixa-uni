"""Server side checks for uploaded files. Mirrors the rules in the browser, because the server never trusts the client."""
import json
import re

SPEC_MAX_BYTES = 500 * 1024
COLLECTION_MAX_BYTES = 5 * 1024 * 1024
MAX_SPECS = 50
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}

TEST_RE = re.compile(r"""(?<![\w.$])test(?:\.(only|skip|fixme))?\s*\(\s*(['"`])((?:\\.|(?!\2)[^\\\n])*)\2""")
IMPORT_RE = re.compile(r"""\bfrom\s+['"]@playwright/test['"]""")
SECRET_RE = re.compile(r"ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[bp]-[A-Za-z0-9]+-[A-Za-z0-9-]+")
SECRET_WARNING = "Possible API key or token found. Move secrets to environment variables"

# Run code from text, so an uploaded test could do anything on the machine running it. A check on the text cannot catch
# every disguise, so the test runner still has to run uploads in a sandbox.
FORBIDDEN_RE = re.compile(r"child_process|worker_threads|process\.(?:binding|dlopen)|(?<![\w$.])eval\s*\(|\bnew\s+Function\s*\(")
# These read local files or run code instead of calling an API.
BAD_URL_RE = re.compile(r"^\s*(javascript|vbscript|data|file|ftp)\s*:", re.I)

# Includes control and invisible characters, which can make a file look like it has a different name.
_BAD_NAME_CHARS = re.compile('[\x00-\x1f\x7f-\x9f​-‏‪-‮⁠-⁯﻿<>:"/\\\\|?*]')
_RESERVED_NAMES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def invalid_name_reason(name: str) -> str | None:
    """Returns why a file name is unsafe to store and run on any operating system, or None when it is fine."""
    if not name or name != name.strip():
        return "File name cannot start or end with a space"
    if len(name) > 200:
        return "File name is too long"
    if _BAD_NAME_CHARS.search(name):
        return 'File name cannot contain / \\ : * ? " < > | or control characters'
    if name.endswith("."):
        return "File name cannot end with a dot"
    if name.split(".")[0].lower() in _RESERVED_NAMES:
        return "That file name is reserved by Windows"
    return None


def _byte_size(text: str) -> int | None:
    """UTF-8 size of the text, or None when it holds characters that cannot be stored (such as a lone surrogate)."""
    try:
        return len(text.encode("utf-8"))
    except UnicodeEncodeError:
        return None


def _regex_end(src: str, start: int) -> int:
    """Where the regular expression opening at start ends, or 0 when its line has no closing slash."""
    i, in_class = start + 1, False
    while i < len(src) and src[i] != "\n":
        c = src[i]
        if c == "\\":
            i += 2
            continue
        if c == "[":
            in_class = True
        elif c == "]":
            in_class = False
        elif c == "/" and not in_class:
            return i + 1
        i += 1
    return 0


def scan(src: str) -> tuple[str, bool]:
    """Blanks out comments (keeping line breaks) and checks that brackets and quotes are closed. A slash straight after
    an opening bracket or an operator starts a regular expression, whose quotes and brackets do not count."""
    pairs = {")": "(", "]": "[", "}": "{"}
    stack, out, quote, i, size, last = [], [], None, 0, len(src), ""
    next_regex = 0  # after a failed try the rest of its line is skipped, or a line of slashes would take hours to check
    while i < size:
        c = src[i]
        nxt = src[i + 1] if i + 1 < size else ""
        if quote:
            out.append(c)
            if c == "\\":
                out.append(nxt)
                i += 2
                continue
            if c == quote:
                quote, last = None, c
            elif c == "\n" and quote != "`":
                return "".join(out) + src[i + 1:], False
            i += 1
            continue
        if c == "/" and nxt == "/":
            while i < size and src[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if c == "/" and nxt == "*":
            end = src.find("*/", i + 2)
            stop = size if end < 0 else end + 2
            out.append(re.sub(r"[^\n]", " ", src[i:stop]))
            if end < 0:
                return "".join(out), False
            i = stop
            continue
        if c == "/" and i >= next_regex and (not last or last in "(,=:[!&|?{;"):
            end = _regex_end(src, i)
            if end:
                out.append(src[i:end])
                i, last = end, "/"
                continue
            next_regex = src.find("\n", i) % (size + 1)
        if c == "\\":
            out.append(c + nxt)
            i += 2
            continue
        if not c.isspace():
            last = c
        if c in "\"'`":
            quote = c
        elif c in "([{":
            stack.append(c)
        elif c in ")]}" and (not stack or stack.pop() != pairs[c]):
            return "".join(out) + src[i:], False
        out.append(c)
        i += 1
    return "".join(out), quote is None and not stack


NOT_REAL_FILE = "This file has no real test content. Add a real file"


def not_real_text(value: str) -> bool:
    """A name that is not real words: no letter at all ("1234", "!!!") or one character over and over ("aaaa").
    The same rule lives in frontend/src/dashboard/validation.ts."""
    s = re.sub(r"\s+", "", value or "")
    return bool(s) and (not re.search(r"[^\W\d_]", s) or (len(s) >= 3 and len(set(s.lower())) == 1))


def analyse_spec(text: str) -> dict:
    clean, balanced = scan(text)
    errors, warnings = [], []
    if not IMPORT_RE.search(clean):
        errors.append("Missing import from '@playwright/test'")
    if forbidden := FORBIDDEN_RE.search(clean):
        errors.append(f"Uses {forbidden.group().rstrip(' (')}, which is not allowed in uploaded tests")
    if not balanced:
        errors.append("File looks incomplete. A bracket or quote is not closed")
    tests, line, counted_to = [], 1, 0
    for m in TEST_RE.finditer(clean):
        line += text.count("\n", counted_to, m.start())  # counted on from the last test: from the top is far too slow
        counted_to = m.start()
        tests.append({"title": m.group(3), "line": line, "mode": m.group(1) or ""})
    if not tests:
        errors.append('No tests found. Add at least one test("title", async ({ page }) => { ... })')
    if len(errors) >= 2 and not tests:
        errors.insert(0, NOT_REAL_FILE + ": a Playwright spec exported from your project")
    fake = [f'"{t["title"]}"' for t in tests if not_real_text(t["title"])]
    if fake:
        errors.append(f"Test names {', '.join(fake[:3])}{' and more' if len(fake) > 3 else ''} are not real. "
                      "Use real names that say what each test checks")
    if any(t["mode"] == "only" for t in tests):
        warnings.append("test.only found. The runner would skip every other test")
    if not re.search(r"\bexpect\s*\(", clean):
        warnings.append("No assertions found. A test without expect() cannot fail")
    if SECRET_RE.search(text):
        warnings.append(SECRET_WARNING)
    return {"errors": errors, "warnings": warnings, "tests": tests}


def validate_spec(name: str, text: str) -> dict:
    errors = []
    reason = invalid_name_reason(name)
    if reason:
        errors.append(reason)
    elif not name.endswith(".spec.ts"):
        errors.append("Only .spec.ts files are accepted")
    elif not name.removesuffix(".spec.ts").strip(". "):
        errors.append("File name needs a name before .spec.ts")
    size = _byte_size(text)
    if size is None:
        errors.append("File contains invalid characters")
    elif not size:
        errors.append("File is empty")
    elif size > SPEC_MAX_BYTES:
        errors.append(f"File is {size // 1024} KB. The limit is {SPEC_MAX_BYTES // 1024} KB")
    if "\x00" in text or "\ufffd" in text:
        errors.append("File is not plain text")
    if errors:
        return {"errors": errors, "warnings": [], "tests": []}
    return analyse_spec(text)


def _aslist(value) -> list:
    return value if isinstance(value, list) else [] if value is None else [value]


def _url_of(request) -> str:
    if isinstance(request, str):
        return request
    url = request.get("url")
    if isinstance(url, str):
        return url
    if isinstance(url, dict):
        if url.get("raw"):
            return str(url["raw"])
        part = lambda p: str(p.get("value", "")) if isinstance(p, dict) else str(p)
        return ".".join(map(part, _aslist(url.get("host")))) + "/" + "/".join(map(part, _aslist(url.get("path"))))
    return ""


def analyse_collection(text: str) -> dict:
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as exc:
        return {"errors": [NOT_REAL_FILE + ": a collection exported from Postman", f"Not valid JSON. {exc}"]}
    if not isinstance(data, dict):
        return {"errors": [NOT_REAL_FILE + ": a collection exported from Postman", "Expected a Postman collection object at the top level"]}
    if isinstance(data.get("values"), list) and not data.get("item"):
        return {"errors": ["This is a Postman environment file. Export the collection instead"]}

    errors, warnings = [], []
    info = data["info"] if isinstance(data.get("info"), dict) else {}
    version = re.search(r"schema\.getpostman\.com/json/collection/v(2\.[01])\.0/", str(info.get("schema") or ""))
    if not version:
        errors.append("Unsupported or missing schema. Export as Collection v2.0 or v2.1")
    if not isinstance(info.get("name"), str) or not info["name"].strip():
        errors.append("Collection has no name")
    elif not_real_text(info["name"]):
        errors.append(f'Collection name "{info["name"]}" is not real. Give it a real name')
    if not isinstance(data.get("item"), list) or not data["item"]:
        return {"errors": errors + ["Collection has no items"]}

    requests, bad, folders = [], [], 0

    def walk(items, path, depth=0):
        nonlocal folders
        if depth > 50:
            bad.append("Folders are nested too deeply")
            return
        for index, raw in enumerate(items):
            item = raw if isinstance(raw, dict) else {}
            name = str(item.get("name") or f"Item {index + 1}")
            if isinstance(item.get("item"), list):
                folders += 1
                walk(item["item"], path + [name], depth + 1)
                continue
            request = item.get("request")
            if not request:
                bad.append(f'"{name}" is neither a folder nor a request')
                continue
            if not isinstance(request, (str, dict)):
                bad.append(f'"{name}" has an unreadable request')
                continue
            method = "GET" if isinstance(request, str) else str(request.get("method") or "GET").upper()
            url = _url_of(request)
            if item.get("name") and not_real_text(str(item["name"])):
                bad.append(f'"{name}" is not a real request name. Use a real name, like "Get products"')
            if method not in METHODS:
                bad.append(f'"{name}" uses unsupported method {method}')
            if not url.replace("/", "").strip():
                bad.append(f'"{name}" has no URL')
            elif scheme := BAD_URL_RE.match(url):
                bad.append(f'"{name}" uses a {scheme.group(1).lower()} address, which is not allowed')
            elif re.search(r"\s", re.sub(r"\{\{[^{}]*\}\}", "", url).split("?")[0].strip()):  # {{base url}} is a variable
                bad.append(f'"{name}" has an address that is not a URL')
            has_tests = any(
                isinstance(e, dict) and e.get("listen") == "test" and isinstance(e.get("script"), dict)
                and "".join(map(str, _aslist(e["script"].get("exec")))).strip()
                for e in _aslist(item.get("event"))
            )
            requests.append({"folder": " / ".join(path), "method": method, "name": name, "url": url, "has_tests": has_tests})

    walk(data["item"], [])
    if not requests:
        errors.append("Collection has no requests")
    errors += bad[:5]
    if len(bad) > 5:
        errors.append(f"and {len(bad) - 5} more request problems")
    bare = sum(1 for r in requests if not r["has_tests"])
    if bare:
        warnings.append(f"{bare} request{'' if bare == 1 else 's'} without a test script. Newman will only check that they respond")
    if SECRET_RE.search(text):
        warnings.append(SECRET_WARNING)
    return {"errors": errors, "warnings": warnings, "requests": requests, "folders": folders}


def validate_collection(name: str, text: str) -> dict:
    errors = []
    reason = invalid_name_reason(name)
    if reason:
        errors.append(reason)
    elif not name.endswith(".json"):
        errors.append("Only .json collection exports are accepted")
    elif not name.removesuffix(".json").strip(". "):
        errors.append("File name needs a name before .json")
    size = _byte_size(text)
    if size is None:
        errors.append("File contains invalid characters")
    elif not size:
        errors.append("File is empty")
    elif size > COLLECTION_MAX_BYTES:
        errors.append(f"File is {size // 1048576} MB. The limit is {COLLECTION_MAX_BYTES // 1048576} MB")
    if "\x00" in text or "\ufffd" in text:
        errors.append("File is not plain text")
    if errors:
        return {"errors": errors}
    return analyse_collection(text)