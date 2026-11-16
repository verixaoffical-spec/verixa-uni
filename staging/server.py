"""Shoplite staging: a small shop to demonstrate Verixa on. It needs nothing but Python.

    python staging/server.py          starts it on http://127.0.0.1:4000
    python staging/server.py 4100     another port

Open /demo to switch three situations on and off, then press Run Now in Verixa:
  * cart bug        the cart total is doubled            -> Verixa reports a real bug (UI test)
  * orders bug      placing an order answers 500         -> Verixa reports a real bug (API test)
  * wishlist page   off: /wishlist answers 404           -> Verixa says "deployment pending", not a bug

The sample tests in samples/test-data/shoplite were written for this shop. Everything is kept in memory,
so a restart puts it back to a healthy shop with no wishlist page.
"""
import json
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PRODUCTS = [{"id": 1, "name": "Notebook", "price": 24.99}, {"id": 2, "name": "Pen set", "price": 9.50},
            {"id": 3, "name": "Desk lamp", "price": 39.00}]
USERS = {"customer@shoplite.test": "Customer123!"}
SWITCHES = {"cart_bug": False, "orders_bug": False, "wishlist_page": False}
TOKENS: dict[str, str] = {}       # token -> email
CARTS: dict[str, list[dict]] = {}  # token -> items

SHOP = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Shoplite</title><style>
body{font:15px/1.5 system-ui,sans-serif;max-width:760px;margin:32px auto;padding:0 16px;color:#1b1b25}
h1{margin:0}header{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}
.card{border:1px solid #ddd;border-radius:10px;padding:14px;margin:10px 0;display:flex;justify-content:space-between;align-items:center;gap:10px}
input,button{font:inherit;padding:8px 10px;border-radius:8px;border:1px solid #bbb}button{background:#4b3fc4;color:#fff;border:0;cursor:pointer}
#message{min-height:22px;color:#a12626;font-weight:600}.row{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}
</style></head><body>
<header><h1>Shoplite</h1><span>Signed in as <b data-testid="user_label" id="user">Guest</b></span></header>
<div class="row"><input data-testid="email_input" id="email" placeholder="Email" autocomplete="off">
<input data-testid="password_input" id="password" type="password" placeholder="Password">
<button data-testid="login_button" id="login">Log in</button></div>
<p data-testid="message" id="message"></p>
<div id="products"></div>
<div class="card"><span>Cart total: <b data-testid="cart_total" id="total">0.00</b></span>
<button data-testid="checkout_button" id="checkout">Checkout</button></div>
<script>
let token = '';
const $ = id => document.getElementById(id);
const say = text => { $('message').textContent = text; };
async function call(path, body) {
  const res = await fetch(path, { method: body ? 'POST' : 'GET', body: body ? JSON.stringify(body) : undefined,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) } });
  return { ok: res.ok, data: await res.json().catch(() => ({})) };
}
async function showCart() { const cart = await call('/api/cart'); if (cart.ok) $('total').textContent = cart.data.total.toFixed(2); }
$('login').onclick = async () => {
  const res = await call('/api/auth/login', { email: $('email').value, password: $('password').value });
  if (!res.ok) return say('Email or password is incorrect');
  token = res.data.token; $('user').textContent = res.data.email; say(''); showCart();
};
$('checkout').onclick = async () => {
  if (!token) return say('Please login first');
  const res = await call('/api/orders', {});
  say(res.ok ? 'Order placed. Thank you!' : 'The order could not be placed'); showCart();
};
call('/api/products').then(res => { for (const p of res.data) {
  const row = document.createElement('div'); row.className = 'card';
  const name = document.createElement('span'); name.textContent = p.name + ', ' + p.price.toFixed(2);
  const add = document.createElement('button'); add.textContent = 'Add to cart'; add.dataset.testid = 'add_to_cart_' + p.id;
  add.onclick = async () => { if (!token) return say('Please login first');
    await call('/api/cart/items', { productId: p.id, quantity: 1 }); say(''); showCart(); };
  row.append(name, add); $('products').append(row); } });
</script></body></html>"""

WISHLIST = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Wishlist</title></head>
<body style="font:15px system-ui;max-width:760px;margin:32px auto"><h1>Wishlist</h1><p>No saved items yet.</p></body></html>"""

DEMO = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Shoplite demo switches</title><style>
body{font:15px/1.6 system-ui,sans-serif;max-width:640px;margin:32px auto;padding:0 16px}label{display:block;padding:12px;border:1px solid #ddd;border-radius:10px;margin:10px 0}
small{display:block;color:#555}</style></head><body><h1>Demo switches</h1>
<p>Change a switch, then press <b>Run Now</b> in Verixa. A restart turns everything off.</p>
<label><input type="checkbox" id="cart_bug"> Cart bug<small>The cart total is doubled. Verixa should report a real bug from the UI test.</small></label>
<label><input type="checkbox" id="orders_bug"> Orders bug<small>Placing an order answers 500. Verixa should report a real bug from the API test.</small></label>
<label><input type="checkbox" id="wishlist_page"> Wishlist page is deployed<small>Off: /wishlist answers 404, so its test is "deployment pending", not a bug.</small></label>
<p><a href="/">Open the shop</a></p>
<script>
fetch('/demo/state').then(r => r.json()).then(state => { for (const [name, on] of Object.entries(state)) {
  const box = document.getElementById(name); box.checked = on;
  box.onchange = () => fetch('/demo/set', { method: 'POST', body: JSON.stringify({ name, on: box.checked }) }); } });
</script></body></html>"""


class Shop(BaseHTTPRequestHandler):
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

    def token(self) -> str | None:
        value = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        return value if value in TOKENS else None

    def cart(self, token: str) -> dict:
        items = CARTS.setdefault(token, [])
        total = sum(next(p["price"] for p in PRODUCTS if p["id"] == i["productId"]) * i["quantity"] for i in items)
        return {"items": items, "total": round(total * (2 if SWITCHES["cart_bug"] else 1), 2)}

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            self.send(200, SHOP, "text/html")
        elif path == "/wishlist" and SWITCHES["wishlist_page"]:
            self.send(200, WISHLIST, "text/html")
        elif path == "/demo":
            self.send(200, DEMO, "text/html")
        elif path == "/demo/state":
            self.send(200, SWITCHES)
        elif path == "/health":
            self.send(200, {"ok": True})
        elif path == "/api/products":
            self.send(200, PRODUCTS)
        elif path == "/api/cart":
            token = self.token()
            self.send(200, self.cart(token)) if token else self.send(401, {"error": "Please login first"})
        else:
            self.send(404, {"error": "Not found"})

    def do_POST(self):
        path, data = self.path.split("?")[0], self.body()
        if path == "/demo/set":
            if data.get("name") in SWITCHES:
                SWITCHES[data["name"]] = bool(data.get("on"))
            return self.send(200, SWITCHES)
        if path == "/api/auth/register":
            email, password = str(data.get("email") or "").lower(), str(data.get("password") or "")
            if "@" not in email or len(password) < 8:
                return self.send(400, {"error": "Enter an email and a password of at least 8 characters"})
            if email in USERS:
                return self.send(409, {"error": "That email is already registered"})
            USERS[email] = password
            return self.send(201, {"email": email})
        if path == "/api/auth/login":
            email = str(data.get("email") or "").lower()
            if USERS.get(email) != data.get("password"):
                return self.send(401, {"error": "Email or password is incorrect"})
            token = secrets.token_hex(16)
            TOKENS[token] = email
            return self.send(200, {"token": token, "email": email})
        token = self.token()
        if path in ("/api/cart/items", "/api/orders") and not token:
            return self.send(401, {"error": "Please login first"})
        if path == "/api/cart/items":
            product, quantity = data.get("productId"), data.get("quantity", 1)
            if not any(p["id"] == product for p in PRODUCTS) or not isinstance(quantity, int) or quantity < 1:
                return self.send(400, {"error": "Unknown product or bad quantity"})
            CARTS.setdefault(token, []).append({"productId": product, "quantity": quantity})
            return self.send(201, self.cart(token))
        if path == "/api/orders":
            if SWITCHES["orders_bug"]:
                return self.send(500, {"error": "Could not save the order"})
            cart = self.cart(token)
            if not cart["items"]:
                return self.send(400, {"error": "The cart is empty"})
            CARTS[token] = []
            return self.send(201, {"status": "PLACED", "total": cart["total"]})
        self.send(404, {"error": "Not found"})


if __name__ == "__main__":
    PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    print(f"Shoplite staging on http://127.0.0.1:{PORT}   switches: http://127.0.0.1:{PORT}/demo", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Shop).serve_forever()
