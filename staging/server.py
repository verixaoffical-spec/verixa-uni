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

The sample tests are in samples/test-data/demo-site. Everything is kept in memory, so a restart puts the site back to
a healthy state with no Docs page.
"""
import json
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PLANS = [("Free", 0), ("Pro", 10), ("Team", 25)]  # name, price per month in dollars
FEATURES = {"Free": ["Up to 3 lists", "Personal tasks", "Email support"],
            "Pro": ["Unlimited lists", "Due dates and reminders", "Priority support"],
            "Team": ["Everything in Pro", "Shared team spaces", "Admin controls"]}
USERS = {"demo@taskflow.test": "Taskflow123!", "api@taskflow.test": "Taskflow123!"}
SWITCHES = {"pricing_bug": False, "contact_bug": False, "tasks_bug": False, "docs_page": False}
TOKENS: dict[str, str] = {}        # token -> email
TASKS: dict[str, list[dict]] = {}  # email -> tasks

STYLE = """
:root{--ink:#0f1222;--muted:#5b6078;--line:#e6e8f0;--soft:#f6f7fb;--brand:#4f46e5;--brand-2:#7c3aed;--ok:#0f8a5f;--bad:#c2312b}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;font:16px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:var(--ink);background:#fff}
a{color:var(--brand);text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:1120px;margin:0 auto;padding:0 20px}
.top{position:sticky;top:0;z-index:5;background:rgba(255,255,255,.85);backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.top .wrap{display:flex;align-items:center;gap:24px;height:64px}
.logo{display:flex;align-items:center;gap:9px;font-weight:800;font-size:19px;color:var(--ink);margin-right:auto}.logo:hover{text-decoration:none}
.logo i{width:28px;height:28px;border-radius:8px;background:linear-gradient(135deg,var(--brand),var(--brand-2));display:grid;place-items:center}
.logo i:after{content:"";width:12px;height:7px;border:3px solid #fff;border-top:0;border-right:0;transform:rotate(-45deg) translate(1px,-2px)}
.top nav{display:flex;gap:22px;font-size:15px}.top nav a{color:var(--muted);font-weight:500}.top nav a:hover{color:var(--ink);text-decoration:none}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;font-family:inherit;font-weight:600;font-size:15px;line-height:1;padding:12px 18px;border-radius:10px;
  border:1px solid transparent;cursor:pointer;background:var(--brand);color:#fff;transition:transform .15s,box-shadow .15s}
.btn:hover{text-decoration:none;transform:translateY(-1px);box-shadow:0 8px 20px -8px rgba(79,70,229,.6)}
.btn.ghost{background:#fff;color:var(--ink);border-color:var(--line)}.btn.ghost:hover{box-shadow:0 6px 16px -10px rgba(15,18,34,.35)}
.btn.small{padding:9px 14px;font-size:14px}
.hero{padding:88px 0 56px;text-align:center;background:radial-gradient(900px 420px at 50% -10%,#ece9ff 0,#fff 70%)}
.pill{display:inline-block;font-size:13px;font-weight:600;color:var(--brand);background:#eef0ff;border-radius:999px;padding:5px 12px;margin-bottom:18px}
.hero h1{font-size:clamp(38px,6vw,64px);line-height:1.05;letter-spacing:-.03em;margin:0 0 18px}
.hero p.lead{font-size:20px;color:var(--muted);max-width:620px;margin:0 auto 30px}.cta{display:flex;gap:12px;justify-content:center;flex-wrap:wrap}
.shot{max-width:860px;margin:56px auto 0;border:1px solid var(--line);border-radius:16px;box-shadow:0 40px 80px -40px rgba(15,18,34,.35);background:#fff;overflow:hidden;text-align:left}
.shot .bar{display:flex;gap:6px;padding:12px 14px;border-bottom:1px solid var(--line);background:var(--soft)}.shot .bar b{width:10px;height:10px;border-radius:50%;background:#d6d9e4}
.shot .rows{padding:18px 22px;display:grid;gap:10px}.shot .row{display:flex;align-items:center;gap:12px;padding:12px 14px;border:1px solid var(--line);border-radius:10px}
.shot .row span{flex:1}.chip{font-size:12px;font-weight:600;padding:3px 9px;border-radius:999px;background:#eef0ff;color:var(--brand)}.chip.g{background:#e6f6ef;color:var(--ok)}
.tick{width:18px;height:18px;border-radius:6px;border:2px solid #c9cdda}.tick.on{background:var(--ok);border-color:var(--ok)}
.logos{padding:30px 0;text-align:center;color:var(--muted);font-size:14px}.logos div{display:flex;gap:40px;justify-content:center;flex-wrap:wrap;margin-top:12px;font-weight:700;color:#9aa0b4;font-size:18px}
section.block{padding:72px 0}section.alt{background:var(--soft)}
h2.title{font-size:clamp(28px,4vw,40px);letter-spacing:-.02em;margin:0 0 10px;text-align:center}p.sub{color:var(--muted);text-align:center;max-width:620px;margin:0 auto 40px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:20px}
.card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:26px}.card h3{margin:14px 0 6px;font-size:19px}.card p{margin:0;color:var(--muted)}
.icon{width:42px;height:42px;border-radius:12px;display:grid;place-items:center;background:#eef0ff;color:var(--brand);font-weight:800}
.quote{max-width:760px;margin:0 auto;text-align:center;font-size:22px;line-height:1.5}.quote small{display:block;margin-top:16px;font-size:15px;color:var(--muted)}
.band{background:linear-gradient(135deg,var(--brand),var(--brand-2));color:#fff;border-radius:20px;padding:48px;text-align:center}
.band h2{margin:0 0 10px;font-size:32px}.band p{margin:0 0 24px;opacity:.9}.band .btn{background:#fff;color:var(--brand)}
.page{padding:56px 0 72px}.page h1{font-size:clamp(34px,5vw,48px);letter-spacing:-.03em;margin:0 0 10px}.page .lead{color:var(--muted);font-size:18px;margin:0 0 32px}
.toggle{display:inline-flex;padding:4px;border:1px solid var(--line);border-radius:12px;background:var(--soft);margin-bottom:32px}
.toggle button{font-family:inherit;font-weight:600;font-size:15px;border:0;background:transparent;color:var(--muted);padding:9px 16px;border-radius:9px;cursor:pointer}
.toggle button[aria-pressed=true]{background:#fff;color:var(--ink);box-shadow:0 2px 8px -2px rgba(15,18,34,.2)}
.plan{position:relative}.plan.pop{border:2px solid var(--brand);box-shadow:0 30px 60px -30px rgba(79,70,229,.45)}
.plan .badge{position:absolute;top:-12px;left:26px;font-size:12px;font-weight:700;color:#fff;background:var(--brand);padding:4px 10px;border-radius:999px}
.card p.price{color:var(--ink);font-size:38px;font-weight:800;letter-spacing:-.02em;margin:10px 0 18px}.plan ul{list-style:none;padding:0;margin:0 0 24px;color:var(--muted)}
.plan li{padding:6px 0 6px 26px;position:relative}.plan li:before{content:"";position:absolute;left:2px;top:13px;width:10px;height:6px;border:2px solid var(--ok);border-top:0;border-right:0;transform:rotate(-45deg)}
.split{display:grid;grid-template-columns:1fr 1.2fr;gap:40px;align-items:start}@media(max-width:820px){.split{grid-template-columns:1fr}.top nav{display:none}}
label{display:block;margin:16px 0 6px;font-weight:600;font-size:14px}
input,textarea{width:100%;font:inherit;padding:11px 13px;border:1px solid #cfd3e0;border-radius:10px;background:#fff;transition:border-color .15s,box-shadow .15s}
input:focus,textarea:focus{outline:none;border-color:var(--brand);box-shadow:0 0 0 4px #eef0ff}
.msg{min-height:24px;font-weight:600;margin:14px 0 0}.msg.error,.error{color:var(--bad)}.msg.ok{color:var(--ok)}
.auth{min-height:calc(100vh - 64px);display:grid;place-items:center;background:radial-gradient(700px 360px at 50% 0,#ece9ff 0,#fff 70%);padding:40px 20px}
.auth .card{width:100%;max-width:420px;padding:34px}.auth h1{margin:0 0 4px;font-size:30px}.hint{color:var(--muted);font-size:14px;margin:0 0 8px}
.app{display:grid;grid-template-columns:240px 1fr;min-height:calc(100vh - 64px)}@media(max-width:820px){.app{grid-template-columns:1fr}.side{display:none}}
.side{border-right:1px solid var(--line);background:var(--soft);padding:24px 16px}.side a{display:block;padding:9px 12px;border-radius:8px;color:var(--muted);font-weight:500}
.side a.on{background:#fff;color:var(--ink);box-shadow:0 1px 3px rgba(15,18,34,.08)}.main{padding:36px 40px}
.add{display:flex;gap:10px;align-items:flex-end}.add div{flex:1}.add label{margin-top:0}
ul.tasks{list-style:none;padding:0;margin:24px 0 0;display:grid;gap:10px}ul.tasks li{display:flex;gap:12px;align-items:center;padding:14px 16px;border:1px solid var(--line);border-radius:12px;background:#fff}
.empty{color:var(--muted);padding:30px;text-align:center;border:1px dashed var(--line);border-radius:12px;margin-top:24px}
.docs{display:grid;grid-template-columns:220px 1fr;gap:40px}.docs nav a{display:block;padding:6px 0;color:var(--muted)}@media(max-width:820px){.docs{grid-template-columns:1fr}}
footer{border-top:1px solid var(--line);padding:40px 0;color:var(--muted);font-size:14px}footer .wrap{display:flex;gap:40px;flex-wrap:wrap;justify-content:space-between}
footer b{color:var(--ink);display:block;margin-bottom:8px}footer a{display:block;color:var(--muted);padding:3px 0}
.switch{display:flex;gap:14px;align-items:flex-start;padding:18px;border:1px solid var(--line);border-radius:12px;margin:12px 0;font-weight:400;background:#fff}
.switch input{width:20px;height:20px;margin-top:3px}.switch b{display:block}
"""

HOME = """<section class="hero"><div class="wrap">
<span class="pill">New: shared team spaces</span>
<h1>Plan less. Finish more.</h1>
<p class="lead">TaskFlow keeps your team's work in one calm place, so everyone knows what is next and nothing slips.</p>
<div class="cta"><a class="btn" href="/pricing">See pricing</a><a class="btn ghost" href="/signin">Start free</a></div>
<div class="shot" aria-hidden="true"><div class="bar"><b></b><b></b><b></b></div><div class="rows">
<div class="row"><i class="tick on"></i><span>Send the launch email</span><em class="chip g">Done</em></div>
<div class="row"><i class="tick"></i><span>Review the Q3 roadmap</span><em class="chip">Today</em></div>
<div class="row"><i class="tick"></i><span>Interview two designers</span><em class="chip">Friday</em></div></div></div>
</div></section>
<div class="logos wrap">Trusted by teams at<div><span>Northwind</span><span>Lumen</span><span>Brightpath</span><span>Cobalt</span><span>Fernway</span></div></div>
<section class="block alt"><div class="wrap"><h2 class="title">Everything a busy team needs</h2>
<p class="sub">Simple enough for one person, strong enough for a whole company.</p><div class="grid">
<div class="card"><div class="icon">1</div><h3>Lists</h3><p>Write a task down in a second and sort it later.</p></div>
<div class="card"><div class="icon">2</div><h3>Focus</h3><p>See only what is due today, and hide the rest.</p></div>
<div class="card"><div class="icon">3</div><h3>Teams</h3><p>Share a space, assign work and see progress at a glance.</p></div>
</div></div></section>
<section class="block"><div class="wrap"><p class="quote">"We moved three tools into TaskFlow in an afternoon. Our Monday meeting is now ten minutes."
<small>Maya Chen, Head of Operations at Northwind</small></p></div></section>
<section class="block" style="padding-top:0"><div class="wrap"><div class="band"><h2>Start in under a minute</h2>
<p>Free for personal use. No card needed.</p><a class="btn" href="/signin">Create your first list</a></div></div></section>"""

PRICING = """<section class="page"><div class="wrap" style="text-align:center">
<h1>Pricing</h1><p class="lead">Simple plans that grow with your team. Pick how you want to pay.</p>
<div class="toggle" role="group" aria-label="Billing period"><button id="monthly" aria-pressed="true">Monthly</button>
<button id="yearly" aria-pressed="false">Yearly (20% off)</button></div>
<div class="grid" id="plans" style="text-align:left"></div>
<p class="hint" style="margin-top:28px">Prices in US dollars. Cancel any time.</p></div></section>
<script>
const features = __FEATURES__;
let plans = [], period = 'monthly';
const show = () => { const box = document.getElementById('plans'); box.textContent = '';
  for (const p of plans) { const card = document.createElement('div'); card.className = 'card plan' + (p.name === 'Pro' ? ' pop' : '');
    if (p.name === 'Pro') { const b = document.createElement('span'); b.className = 'badge'; b.textContent = 'Most popular'; card.append(b); }
    const name = document.createElement('h2'); name.textContent = p.name; name.style.margin = '0';
    const price = document.createElement('p'); price.className = 'price';
    price.textContent = '$' + p[period] + (period === 'monthly' ? ' / month' : ' / year');
    const list = document.createElement('ul');
    for (const f of features[p.name]) { const li = document.createElement('li'); li.textContent = f; list.append(li); }
    const go = document.createElement('a'); go.className = 'btn' + (p.name === 'Pro' ? '' : ' ghost'); go.href = '/signin';
    go.textContent = p.monthly ? 'Choose ' + p.name : 'Start free'; go.style.width = '100%';
    card.append(name, price, list, go); box.append(card); }
  for (const id of ['monthly', 'yearly']) document.getElementById(id).setAttribute('aria-pressed', String(id === period)); };
for (const id of ['monthly', 'yearly']) document.getElementById(id).onclick = () => { period = id; show(); };
fetch('/api/plans').then(r => r.json()).then(data => { plans = data; show(); });
</script>"""

DOCS = """<section class="page"><div class="wrap docs"><nav aria-label="Docs"><b>Getting started</b><a href="#lists">Lists</a>
<a href="#tasks">Tasks</a><a href="#teams">Teams</a></nav><article><h1>Documentation</h1>
<p class="lead">How to create a list, add a task and share it with your team.</p>
<h2 id="lists">Create a list</h2><p>Open the dashboard and give your list a name. Lists keep related work together.</p>
<h2 id="tasks">Tasks</h2><p>Type the task in the New task box and press Add task. It appears at the end of the list.</p>
<h2 id="teams">Share with your team</h2><p>On the Team plan, invite people by email and they see the same lists.</p></article></div></section>"""

CONTACT = """<section class="page"><div class="wrap split"><div><h1>Contact us</h1>
<p class="lead">Questions about plans, a demo for your team, or help with your account. We answer within one working day.</p>
<div class="card"><h3 style="margin-top:0">Sales</h3><p>sales@taskflow.example</p></div>
<div class="card" style="margin-top:16px"><h3 style="margin-top:0">Support</h3><p>help@taskflow.example</p></div></div>
<div class="card"><form id="form" novalidate>
<label for="name">Name</label><input id="name" autocomplete="name">
<label for="email">Email</label><input id="email" type="email" autocomplete="email">
<label for="message">Message</label><textarea id="message" rows="5"></textarea>
<p style="margin:20px 0 0"><button class="btn" type="submit">Send message</button></p><p id="msg" class="msg" role="status"></p></form></div>
</div></section>
<script>
const $ = id => document.getElementById(id);
$('form').onsubmit = async event => { event.preventDefault();
  const body = { name: $('name').value.trim(), email: $('email').value.trim(), message: $('message').value.trim() }, say = (text, cls) => {
    $('msg').textContent = text; $('msg').className = 'msg ' + cls; };
  if (!body.name || !body.email || !body.message) return say('Please fill in every field', 'error');
  const res = await fetch('/api/contact', { method: 'POST', body: JSON.stringify(body) });
  res.ok ? say('Thanks, we got your message', 'ok') : say('Your message could not be sent', 'error'); };
</script>"""

SIGNIN = """<section class="auth"><div class="card"><h1>Sign in</h1><p class="hint">Welcome back. Use the demo account demo@taskflow.test.</p>
<form id="form"><label for="email">Email</label><input id="email" type="email" autocomplete="off">
<label for="password">Password</label><input id="password" type="password">
<p style="margin:22px 0 0"><button class="btn" type="submit" style="width:100%">Sign in</button></p>
<p id="msg" role="alert" class="msg error"></p></form></div></section>
<script>
const $ = id => document.getElementById(id);
$('form').onsubmit = async event => { event.preventDefault();
  const res = await fetch('/api/auth/login', { method: 'POST', body: JSON.stringify({ email: $('email').value, password: $('password').value }) });
  if (!res.ok) return $('msg').textContent = 'Email or password is incorrect';
  const data = await res.json(); sessionStorage.setItem('token', data.token); sessionStorage.setItem('email', data.email);
  location.href = '/app'; };
</script>"""

APP = """<div class="app"><aside class="side"><a class="on" href="/app">My tasks</a><a href="/docs">Help</a><a href="/pricing">Upgrade</a></aside>
<section class="main"><h1 style="margin:0">Your tasks</h1><p id="who" class="hint"></p>
<form id="form" class="add"><div><label for="title">New task</label><input id="title" placeholder="What needs doing?"></div>
<button class="btn" type="submit">Add task</button><button type="button" id="out" class="btn ghost">Sign out</button></form>
<ul id="tasks" class="tasks"></ul><p id="none" class="empty">No tasks yet. Add your first one above.</p></section></div>
<script>
const token = sessionStorage.getItem('token');
if (!token) location.href = '/signin';
document.getElementById('who').textContent = 'Signed in as ' + sessionStorage.getItem('email');
const call = (body) => fetch('/api/tasks', { method: body ? 'POST' : 'GET', body: body ? JSON.stringify(body) : undefined,
  headers: { Authorization: 'Bearer ' + token } }).then(r => r.json());
const load = async () => { const list = document.getElementById('tasks'); list.textContent = ''; const tasks = await call();
  for (const t of tasks) { const li = document.createElement('li'); const box = document.createElement('i'); box.className = 'tick';
    const text = document.createElement('span'); text.textContent = t.title; li.append(box, text); list.append(li); }
  document.getElementById('none').hidden = tasks.length > 0; };
document.getElementById('form').onsubmit = async event => { event.preventDefault();
  const box = document.getElementById('title');
  if (!box.value.trim()) return; await call({ title: box.value.trim() }); box.value = ''; load(); };
document.getElementById('out').onclick = () => { sessionStorage.clear(); location.href = '/signin'; };
load();
</script>"""

DEMO = """<section class="page"><div class="wrap" style="max-width:720px"><h1>Demo switches</h1>
<p class="lead">This page is for the Verixa demo, not part of the product. Change a switch, then press <b>Run Now</b> in Verixa.
A restart turns everything off.</p>
<label class="switch"><input type="checkbox" id="pricing_bug"><span><b>Pricing bug</b>The yearly price forgets the 20% discount.</span></label>
<label class="switch"><input type="checkbox" id="contact_bug"><span><b>Contact bug</b>Sending the contact form fails with a server error.</span></label>
<label class="switch"><input type="checkbox" id="tasks_bug"><span><b>Tasks bug</b>A new task is accepted but not saved.</span></label>
<label class="switch"><input type="checkbox" id="docs_page"><span><b>Docs page is deployed</b>Off: /docs answers 404, so its test is "deployment pending".</span></label>
<p><a href="/">Open the site</a></p></div></section>
<script>
fetch('/demo/state').then(r => r.json()).then(state => { for (const [name, on] of Object.entries(state)) {
  const box = document.getElementById(name); box.checked = on;
  box.onchange = () => fetch('/demo/set', { method: 'POST', body: JSON.stringify({ name, on: box.checked }) }); } });
</script>"""

NOT_FOUND = """<section class="page"><div class="wrap" style="text-align:center"><p class="pill">404</p><h1>Page not found</h1>
<p class="lead">The page you are looking for does not exist or has moved.</p><a class="btn" href="/">Back to the home page</a></div></section>"""

PAGES = {  # path: (title, body, show the footer)
    "/": ("TaskFlow: plan less, finish more", HOME, True),
    "/pricing": ("Pricing | TaskFlow", PRICING.replace("__FEATURES__", json.dumps(FEATURES)), True),
    "/docs": ("Documentation | TaskFlow", DOCS, True),
    "/contact": ("Contact | TaskFlow", CONTACT, True),
    "/signin": ("Sign in | TaskFlow", SIGNIN, False),
    "/app": ("Your tasks | TaskFlow", APP, False),
    "/demo": ("Demo switches | TaskFlow", DEMO, True),
}
FOOTER = """<footer><div class="wrap"><div><span class="logo"><i></i>TaskFlow</span><p>Plan less. Finish more.</p><p>© 2026 TaskFlow demo site</p></div>
<div><b>Product</b><a href="/pricing">Pricing</a>__DOCS__<a href="/signin">Sign in</a></div>
<div><b>Company</b><a href="/contact">Contact</a><a href="/">About</a></div></div></footer>"""


def render(path: str, status_page: str | None = None) -> str:
    title, body, footer = ("Page not found | TaskFlow", NOT_FOUND, True) if status_page else PAGES[path]
    docs = '<a href="/docs">Docs</a>' if SWITCHES["docs_page"] else ""
    nav = (f'<header class="top"><div class="wrap"><a class="logo" href="/"><i></i>TaskFlow</a><nav aria-label="Main">'
           f'<a href="/">Product</a><a href="/pricing">Pricing</a>{docs}<a href="/contact">Contact</a></nav>'
           f'<a class="btn ghost small" href="/signin">Sign in</a></div></header>')
    foot = FOOTER.replace("__DOCS__", docs) if footer else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{title}</title><meta name="description" content="TaskFlow keeps your team\'s tasks in one calm place.">'
            f"<style>{STYLE}</style></head><body>{nav}<main>{body}</main>{foot}</body></html>")


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
            self.send(404, render(path, status_page="404"), "text/html")

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
