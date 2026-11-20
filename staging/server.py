"""TaskFlow: a small website to demonstrate Verixa on. It needs nothing but Python.

    python staging/server.py          starts it on http://127.0.0.1:4000
    python staging/server.py 4100     another port

TaskFlow is an ordinary website with pages, a form, a sign in, a dashboard and an API. It is not a shop: Verixa tests
whatever website it is pointed at, and this one only gives it something to find. Open /demo to switch four situations
on and off, then press Run Now in Verixa:

  * pricing bug   the yearly price on the Pricing page is wrong       -> a real bug found by a screen test
  * contact bug   sending the contact form fails with a server error  -> a real bug found by a screen test and an API test
  * tasks bug     a new task is not saved                             -> a real bug found by a screen test and an API test
  * docs page     off: /docs answers 404, so its test is "deployment pending" and not a bug

The sample tests are in samples/test-data/demo-site. Everything is kept in memory, so a restart puts the site back to
a healthy state with no Docs page.
"""
import json
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PLANS = [("Free", 0), ("Pro", 10), ("Team", 25)]  # name, price per month in dollars
USERS = {"demo@taskflow.test": "Taskflow123!", "api@taskflow.test": "Taskflow123!"}
SWITCHES = {"pricing_bug": False, "contact_bug": False, "tasks_bug": False, "docs_page": False}
TOKENS: dict[str, str] = {}        # token -> email
TASKS: dict[str, list[dict]] = {}  # email -> tasks

STYLE = """body{font:16px/1.6 system-ui,sans-serif;margin:0;color:#1b1b25}header,main,footer{max-width:820px;margin:0 auto;padding:16px}
header{display:flex;gap:18px;align-items:center;flex-wrap:wrap;border-bottom:1px solid #e3e3ea}header strong{margin-right:auto}
a{color:#4b3fc4}h1{font-size:34px;margin:24px 0 8px}.card{border:1px solid #e3e3ea;border-radius:12px;padding:16px;margin:12px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}label{display:block;margin:12px 0 4px;font-weight:600}
input,textarea{width:100%;box-sizing:border-box;font:inherit;padding:9px 10px;border:1px solid #b9b9c6;border-radius:8px}
button,.button{font:inherit;background:#4b3fc4;color:#fff;border:0;border-radius:8px;padding:9px 16px;cursor:pointer;text-decoration:none;display:inline-block}
button.plain{background:#fff;color:#4b3fc4;border:1px solid #4b3fc4}button[aria-pressed=true]{background:#1b1b25;color:#fff}
.error{color:#a12626;font-weight:600}.ok{color:#1f7a4d;font-weight:600}.price{font-size:28px;font-weight:700;margin:4px 0}footer{color:#666;font-size:14px}"""

PAGES = {
    "/": ("TaskFlow: plan less, finish more", """<h1>Plan less. Finish more.</h1>
<p>TaskFlow keeps your team's tasks in one calm place.</p><p><a class="button" href="/pricing">See pricing</a></p>
<div class="grid"><div class="card"><h2>Lists</h2><p>Write a task down in a second.</p></div>
<div class="card"><h2>Focus</h2><p>See only what is next.</p></div><div class="card"><h2>Teams</h2><p>Share the work.</p></div></div>"""),
    "/pricing": ("Pricing | TaskFlow", """<h1>Pricing</h1><p>Pick how you want to pay.</p>
<div role="group" aria-label="Billing period"><button id="monthly" aria-pressed="true">Monthly</button>
<button id="yearly" aria-pressed="false" class="plain">Yearly (20% off)</button></div><div class="grid" id="plans"></div>
<script>
let plans = [], period = 'monthly';
const show = () => { const box = document.getElementById('plans'); box.textContent = '';
  for (const p of plans) { const card = document.createElement('div'); card.className = 'card';
    const name = document.createElement('h2'); name.textContent = p.name;
    const price = document.createElement('p'); price.className = 'price';
    price.textContent = '$' + p[period] + (period === 'monthly' ? ' / month' : ' / year');
    card.append(name, price); box.append(card); }
  for (const id of ['monthly', 'yearly']) document.getElementById(id).setAttribute('aria-pressed', String(id === period)); };
for (const id of ['monthly', 'yearly']) document.getElementById(id).onclick = () => { period = id; show(); };
fetch('/api/plans').then(r => r.json()).then(data => { plans = data; show(); });
</script>"""),
    "/docs": ("Documentation | TaskFlow", "<h1>Documentation</h1><p>How to create a list, add a task and share it with your team.</p>"),
    "/contact": ("Contact | TaskFlow", """<h1>Contact us</h1><form id="form" novalidate>
<label for="name">Name</label><input id="name"><label for="email">Email</label><input id="email" type="email">
<label for="message">Message</label><textarea id="message" rows="4"></textarea><p><button type="submit">Send message</button></p>
<p id="msg" role="status"></p></form>
<script>
const $ = id => document.getElementById(id);
$('form').onsubmit = async event => { event.preventDefault();
  const body = { name: $('name').value.trim(), email: $('email').value.trim(), message: $('message').value.trim() }, say = (text, cls) => {
    $('msg').textContent = text; $('msg').className = cls; };
  if (!body.name || !body.email || !body.message) return say('Please fill in every field', 'error');
  const res = await fetch('/api/contact', { method: 'POST', body: JSON.stringify(body) });
  res.ok ? say('Thanks, we got your message', 'ok') : say('Your message could not be sent', 'error'); };
</script>"""),
    "/signin": ("Sign in | TaskFlow", """<h1>Sign in</h1><form id="form"><label for="email">Email</label><input id="email" type="email" autocomplete="off">
<label for="password">Password</label><input id="password" type="password"><p><button type="submit">Sign in</button></p>
<p id="msg" role="alert" class="error"></p></form>
<script>
const $ = id => document.getElementById(id);
$('form').onsubmit = async event => { event.preventDefault();
  const res = await fetch('/api/auth/login', { method: 'POST', body: JSON.stringify({ email: $('email').value, password: $('password').value }) });
  if (!res.ok) return $('msg').textContent = 'Email or password is incorrect';
  const data = await res.json(); sessionStorage.setItem('token', data.token); sessionStorage.setItem('email', data.email);
  location.href = '/app'; };
</script>"""),
    "/app": ("Your tasks | TaskFlow", """<h1>Your tasks</h1><p id="who"></p><form id="form"><label for="title">New task</label><input id="title">
<p><button type="submit">Add task</button> <button type="button" id="out" class="plain">Sign out</button></p></form><ul id="tasks"></ul>
<script>
const token = sessionStorage.getItem('token');
if (!token) location.href = '/signin';
document.getElementById('who').textContent = 'Signed in as ' + sessionStorage.getItem('email');
const call = (body) => fetch('/api/tasks', { method: body ? 'POST' : 'GET', body: body ? JSON.stringify(body) : undefined,
  headers: { Authorization: 'Bearer ' + token } }).then(r => r.json());
const load = async () => { const list = document.getElementById('tasks'); list.textContent = '';
  for (const t of await call()) { const li = document.createElement('li'); li.textContent = t.title; list.append(li); } };
document.getElementById('form').onsubmit = async event => { event.preventDefault();
  const box = document.getElementById('title');
  if (!box.value.trim()) return; await call({ title: box.value.trim() }); box.value = ''; load(); };
document.getElementById('out').onclick = () => { sessionStorage.clear(); location.href = '/signin'; };
load();
</script>"""),
    "/demo": ("Demo switches | TaskFlow", """<h1>Demo switches</h1><p>Change a switch, then press <b>Run Now</b> in Verixa. A restart turns everything off.</p>
<label><input type="checkbox" id="pricing_bug"> Pricing bug: the yearly price is wrong</label>
<label><input type="checkbox" id="contact_bug"> Contact bug: sending the contact form fails</label>
<label><input type="checkbox" id="tasks_bug"> Tasks bug: a new task is not saved</label>
<label><input type="checkbox" id="docs_page"> Docs page is deployed (off: /docs answers 404)</label>
<script>
fetch('/demo/state').then(r => r.json()).then(state => { for (const [name, on] of Object.entries(state)) {
  const box = document.getElementById(name); box.checked = on;
  box.onchange = () => fetch('/demo/set', { method: 'POST', body: JSON.stringify({ name, on: box.checked }) }); } });
</script>"""),
}


def render(path: str) -> str:
    title, body = PAGES[path]
    docs = '<a href="/docs">Docs</a>' if SWITCHES["docs_page"] else ""
    nav = f'<header><strong>TaskFlow</strong><a href="/">Home</a><a href="/pricing">Pricing</a>{docs}<a href="/contact">Contact</a><a href="/signin">Sign in</a></header>'
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{title}</title><style>{STYLE}</style></head><body>{nav}<main>{body}</main><footer>© TaskFlow demo site</footer></body></html>")


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
            self.send(404, "<!doctype html><title>Page not found</title><h1>Page not found</h1>", "text/html")

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
