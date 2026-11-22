"""TaskFlow: a small website to demonstrate Verixa on. It needs nothing but Python.

    python staging/server.py          starts it on http://127.0.0.1:4000
    python staging/server.py 4100     another port

TaskFlow looks and behaves like a real product website: a home page, pricing, docs, a contact form, a sign in, a task
dashboard and a JSON API. It is not a shop: Verixa tests whatever website it is pointed at, and this one only gives it
something to find. Open /demo to switch four situations on and off, then press Run Now in Verixa:

  * pricing bug   the yearly price on the Pricing page is wrong       -> a real bug found by a screen test and an API test
  * contact bug   sending the contact form fails with a server error  -> a real bug found by a screen test and an API test
  * tasks bug     a new task is not saved                             -> a real bug found by a screen test and an API test
  * docs page     off: /docs answers 404, so its test is "deployment pending" and not a bug

The pages, layout and styles are in staging/site. The sample tests are in samples/test-data/demo-site. Everything is kept in memory, so a restart puts the site back to
a healthy state with no Docs page.
"""
import json
import secrets
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PLANS = [("Free", 0), ("Pro", 10), ("Team", 25)]  # name, price per month in dollars
FEATURES = {"Free": ["Up to 3 people", "3 projects", "Today view and reminders"],
            "Pro": ["Up to 10 people", "Unlimited projects", "Boards, due dates and recurring tasks", "Read-only boards for clients"],
            "Team": ["Unlimited people", "Everything in Pro", "Several teams in one workspace", "Admin controls and single sign-on"]}
USERS = {"demo@taskflow.test": "Taskflow123!", "api@taskflow.test": "Taskflow123!"}
SWITCHES = {"pricing_bug": False, "contact_bug": False, "tasks_bug": False, "docs_page": False}
TOKENS: dict[str, str] = {}        # token -> email
TASKS: dict[str, list[dict]] = {}  # email -> tasks

SITE = Path(__file__).resolve().parent / "site"
PAGES = {  # path: (title, page file, body class, footer)
    "/": ("TaskFlow: the task manager for small teams", "home", "home", True),
    "/pricing": ("Pricing | TaskFlow", "pricing", "", True),
    "/docs": ("Documentation | TaskFlow", "docs", "", True),
    "/contact": ("Contact | TaskFlow", "contact", "", True),
    "/signin": ("Sign in | TaskFlow", "signin", "", False),
    "/app": ("Your tasks | TaskFlow", "app", "", False),
    "/demo": ("Demo switches | TaskFlow", "demo", "", True),
}


def render(path: str | None) -> str:
    """One page in the shared layout. Files are read on every request, so an edit shows without a restart."""
    title, name, body_class, footer = PAGES[path] if path else ("Page not found | TaskFlow", "notfound", "", True)
    docs = '<a href="/docs">Docs</a>' if SWITCHES["docs_page"] else ""
    body = (SITE / "pages" / f"{name}.html").read_text(encoding="utf-8").replace("{{features}}", json.dumps(FEATURES))
    foot = (SITE / "footer.html").read_text(encoding="utf-8").replace("{{docs_link}}", docs) if footer else ""
    page = (SITE / "layout.html").read_text(encoding="utf-8")
    for key, value in (("title", title), ("body_class", body_class), ("docs_link", docs), ("footer", foot), ("body", body)):
        page = page.replace("{{" + key + "}}", value)
    return page


def plans() -> list[dict]:
    yearly = (lambda m: m * 12) if SWITCHES["pricing_bug"] else (lambda m: round(m * 12 * 0.8))  # the bug forgets the discount
    return [{"name": name, "monthly": monthly, "yearly": yearly(monthly)} for name, monthly in PLANS]


class Site(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code: int, body, kind: str = "application/json") -> None:
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", kind + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def body(self) -> dict:
        try:
            data = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 10_000)) or b"{}")
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}

    def user(self) -> str | None:
        return TOKENS.get((self.headers.get("Authorization") or "").removeprefix("Bearer ").strip())

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in PAGES and (path != "/docs" or SWITCHES["docs_page"]):
            self.send(200, render(path), "text/html")
        elif path == "/assets/site.css":
            self.send(200, (SITE / "site.css").read_text(encoding="utf-8"), "text/css")
        elif path == "/health":
            self.send(200, {"ok": True})
        elif path == "/demo/state":
            self.send(200, SWITCHES)
        elif path == "/api/plans":
            self.send(200, plans())
        elif path == "/api/tasks":
            email = self.user()
            self.send(200, TASKS.get(email, [])) if email else self.send(401, {"error": "Sign in first"})
        elif path.startswith("/api/") or path.endswith((".js", ".css", ".ico")):
            self.send(404, {"error": "Not found"})
        else:
            self.send(404, render(None), "text/html")

    def do_POST(self):
        path, data = self.path.split("?")[0], self.body()
        if path == "/demo/set":
            if data.get("name") in SWITCHES:
                SWITCHES[data["name"]] = bool(data.get("on"))
            return self.send(200, SWITCHES)
        if path == "/api/contact":
            fields = [str(data.get(k) or "").strip() for k in ("name", "email", "message")]
            if not all(fields) or "@" not in fields[1]:
                return self.send(400, {"error": "Name, a valid email and a message are needed"})
            if SWITCHES["contact_bug"]:
                return self.send(500, {"error": "Could not save the message"})
            return self.send(201, {"ok": True})
        if path == "/api/auth/login":
            email = str(data.get("email") or "").lower()
            if USERS.get(email) != data.get("password"):
                return self.send(401, {"error": "Email or password is incorrect"})
            token = secrets.token_hex(16)
            TOKENS[token] = email
            return self.send(200, {"token": token, "email": email})
        if path == "/api/tasks":
            email = self.user()
            if not email:
                return self.send(401, {"error": "Sign in first"})
            title = str(data.get("title") or "").strip()
            if not title:
                return self.send(400, {"error": "A task needs a title"})
            task = {"id": len(TASKS.get(email, [])) + 1, "title": title[:200]}
            if not SWITCHES["tasks_bug"]:  # the bug answers 201 but forgets to save it
                TASKS.setdefault(email, []).append(task)
            return self.send(201, task)
        self.send(404, {"error": "Not found"})


if __name__ == "__main__":
    PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    print(f"TaskFlow staging on http://127.0.0.1:{PORT}   switches: http://127.0.0.1:{PORT}/demo", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Site).serve_forever()
