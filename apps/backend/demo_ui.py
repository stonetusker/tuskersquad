"""
Demo UI — served at GET /demo
A rich single-page shopping demo that showcases the e-commerce app.
Agents probe this UI during reviews.
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

DEMO_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ShopDemo — AI-tested storefront</title>
<style>
  /* ── Design tokens ─────────────────────────────────────────────── */
  :root {
    --ink:      #1A1A2E;
    --ink-2:    #16213E;
    --ink-3:    #0F3460;
    --accent:   #E94560;
    --accent-2: #533483;
    --surface:  #F5F5F5;
    --white:    #FFFFFF;
    --muted:    #6B7280;
    --border:   #E5E7EB;
    --success:  #10B981;
    --warning:  #F59E0B;
    --danger:   #EF4444;
    --radius:   10px;
    --shadow:   0 4px 20px rgba(26,26,46,0.12);
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: var(--surface);
    color: var(--ink);
    min-height: 100vh;
  }

  /* ── Header ───────────────────────────────────────────────────── */
  .header {
    background: linear-gradient(135deg, var(--ink) 0%, var(--ink-2) 50%, var(--ink-3) 100%);
    color: var(--white);
    padding: 0 32px;
    height: 60px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 100;
    border-bottom: 2px solid var(--accent);
    box-shadow: 0 2px 16px rgba(233,69,96,0.2);
  }

  .header-logo {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .logo-icon {
    width: 32px; height: 32px;
    background: var(--accent);
    border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    font-size: 18px; font-weight: 900; color: white;
  }

  .logo-text { font-size: 18px; font-weight: 800; letter-spacing: -0.02em; }
  .logo-sub  { font-size: 10px; color: rgba(255,255,255,0.5); letter-spacing: 0.08em; }

  .header-actions { display: flex; gap: 12px; align-items: center; }

  .cart-btn {
    background: rgba(255,255,255,0.1);
    border: 1px solid rgba(255,255,255,0.2);
    color: white;
    padding: 7px 16px;
    border-radius: 8px;
    cursor: pointer;
    font-size: 13px;
    font-weight: 600;
    display: flex; align-items: center; gap: 6px;
    transition: background 0.15s;
  }
  .cart-btn:hover { background: rgba(255,255,255,0.2); }

  .cart-count {
    background: var(--accent);
    color: white;
    border-radius: 10px;
    padding: 1px 7px;
    font-size: 11px;
    font-weight: 800;
    min-width: 20px;
    text-align: center;
  }

  /* ── Main ──────────────────────────────────────────────────────── */
  .main { max-width: 1100px; margin: 0 auto; padding: 32px 24px; }

  /* ── Hero ──────────────────────────────────────────────────────── */
  .hero {
    background: linear-gradient(135deg, var(--ink-2) 0%, var(--accent-2) 100%);
    border-radius: 16px;
    padding: 40px 48px;
    color: white;
    margin-bottom: 40px;
    position: relative;
    overflow: hidden;
  }
  .hero::after {
    content: '';
    position: absolute;
    right: -60px; top: -60px;
    width: 240px; height: 240px;
    border-radius: 50%;
    background: rgba(233,69,96,0.15);
  }
  .hero-label {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.12em;
    color: rgba(255,255,255,0.6);
    text-transform: uppercase;
    margin-bottom: 12px;
  }
  .hero-title {
    font-size: 32px; font-weight: 900;
    line-height: 1.2;
    margin-bottom: 10px;
    letter-spacing: -0.02em;
  }
  .hero-sub { font-size: 15px; color: rgba(255,255,255,0.7); max-width: 480px; }

  /* ── Auth panel ────────────────────────────────────────────────── */
  .auth-row {
    display: flex;
    gap: 10px;
    margin-top: 24px;
    flex-wrap: wrap;
  }
  .auth-input {
    padding: 10px 14px;
    border-radius: 8px;
    border: none;
    font-size: 13px;
    background: rgba(255,255,255,0.15);
    color: white;
    outline: none;
    width: 190px;
    backdrop-filter: blur(8px);
  }
  .auth-input::placeholder { color: rgba(255,255,255,0.45); }
  .auth-input:focus { background: rgba(255,255,255,0.25); }

  .btn {
    padding: 10px 22px;
    border: none;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 700;
    cursor: pointer;
    transition: all 0.15s;
    display: inline-flex; align-items: center; gap: 6px;
  }
  .btn-accent { background: var(--accent); color: white; }
  .btn-accent:hover { opacity: 0.88; transform: translateY(-1px); }
  .btn-outline { background: rgba(255,255,255,0.12); color: white; border: 1px solid rgba(255,255,255,0.25); }
  .btn-outline:hover { background: rgba(255,255,255,0.2); }

  .auth-status {
    font-size: 12px;
    color: rgba(255,255,255,0.7);
    display: flex; align-items: center; gap: 6px;
    margin-top: 10px;
  }
  .auth-dot { width: 8px; height: 8px; border-radius: 50%; background: #ccc; }
  .auth-dot.ok    { background: var(--success); box-shadow: 0 0 6px var(--success); }
  .auth-dot.error { background: var(--danger); }

  /* ── Section ───────────────────────────────────────────────────── */
  .section-title {
    font-size: 20px; font-weight: 800;
    color: var(--ink);
    margin-bottom: 20px;
    display: flex; align-items: center; gap: 10px;
  }

  /* ── Products grid ─────────────────────────────────────────────── */
  .products-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 20px;
    margin-bottom: 40px;
  }

  .product-card {
    background: var(--white);
    border-radius: var(--radius);
    border: 1px solid var(--border);
    overflow: hidden;
    transition: box-shadow 0.2s, transform 0.15s;
    cursor: pointer;
  }
  .product-card:hover {
    box-shadow: var(--shadow);
    transform: translateY(-3px);
  }

  .product-img {
    height: 160px;
    display: flex; align-items: center; justify-content: center;
    font-size: 64px;
    background: linear-gradient(135deg, #F8F9FF 0%, #EEF2FF 100%);
  }

  .product-body { padding: 16px; }
  .product-name { font-weight: 700; font-size: 15px; margin-bottom: 4px; }
  .product-price {
    font-size: 20px; font-weight: 900;
    color: var(--ink-3);
    margin-bottom: 12px;
  }
  .product-price .currency { font-size: 13px; font-weight: 600; vertical-align: super; }

  .add-btn {
    width: 100%;
    background: var(--ink);
    color: white;
    padding: 10px;
    border: none;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 700;
    cursor: pointer;
    transition: background 0.15s;
  }
  .add-btn:hover { background: var(--ink-3); }

  /* ── Cart ──────────────────────────────────────────────────────── */
  .cart-section {
    background: var(--white);
    border-radius: var(--radius);
    border: 1px solid var(--border);
    padding: 24px;
    margin-bottom: 32px;
    box-shadow: var(--shadow);
  }

  .cart-empty {
    text-align: center; padding: 24px;
    color: var(--muted); font-size: 14px;
  }

  .cart-items { display: flex; flex-direction: column; gap: 10px; margin-bottom: 20px; }

  .cart-item {
    display: flex; align-items: center; gap: 14px;
    padding: 12px 14px; background: #F9FAFB;
    border-radius: 8px; border: 1px solid var(--border);
  }
  .cart-item-icon { font-size: 24px; }
  .cart-item-name { flex: 1; font-weight: 600; font-size: 14px; }
  .cart-item-qty  { color: var(--muted); font-size: 13px; }
  .cart-item-price { font-weight: 800; font-size: 15px; color: var(--ink-3); }

  .cart-total {
    display: flex; justify-content: space-between; align-items: center;
    padding: 16px 14px;
    background: var(--ink);
    border-radius: 8px;
    color: white;
    margin-bottom: 16px;
  }
  .cart-total-label { font-size: 14px; font-weight: 600; }
  .cart-total-amount { font-size: 24px; font-weight: 900; }

  /* ── Toast ─────────────────────────────────────────────────────── */
  #toast {
    position: fixed; bottom: 24px; right: 24px;
    padding: 14px 20px;
    border-radius: 10px;
    font-size: 14px; font-weight: 600;
    display: flex; align-items: center; gap: 8px;
    opacity: 0; pointer-events: none;
    transition: opacity 0.3s, transform 0.3s;
    transform: translateY(12px);
    z-index: 999;
  }
  #toast.show { opacity: 1; transform: translateY(0); }
  #toast.ok   { background: var(--success); color: white; }
  #toast.err  { background: var(--danger);  color: white; }
  #toast.warn { background: var(--warning); color: white; }

  /* ── Status bar ────────────────────────────────────────────────── */
  .status-bar {
    background: rgba(26,26,46,0.04);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px 16px;
    font-size: 12px;
    color: var(--muted);
    margin-top: 32px;
    display: flex; gap: 24px; flex-wrap: wrap;
  }
  .status-item { display: flex; gap: 6px; align-items: center; }
  .status-dot-sm { width: 6px; height: 6px; border-radius: 50%; }

  /* ── Bug alert banner ──────────────────────────────────────────── */
  .bug-banner {
    background: #FFF5F5; border: 1px solid #FECACA;
    border-radius: 8px; padding: 12px 16px;
    margin-bottom: 20px;
    font-size: 13px; color: #991B1B;
    display: flex; align-items: center; gap: 10px;
  }
</style>
</head>
<body>

<header class="header">
  <div class="header-logo">
    <div class="logo-icon">🛒</div>
    <div>
      <div class="logo-text">ShopDemo</div>
      <div class="logo-sub">AI-GOVERNED STOREFRONT</div>
    </div>
  </div>
  <div class="header-actions">
    <button class="cart-btn" onclick="toggleCart()">
      🛍 Cart <span class="cart-count" id="cartCount">0</span>
    </button>
  </div>
</header>

<main class="main">

  <!-- Hero with Auth -->
  <div class="hero">
    <div class="hero-label">🔬 TuskerSquad Demo Target</div>
    <div class="hero-title">The AI-reviewed storefront</div>
    <div class="hero-sub">This app is continuously reviewed by the 8-agent AI pipeline. Try checkout — agents test pricing, security, and latency in real time.</div>
    <div class="auth-row">
      <input id="emailInput"    class="auth-input" type="email"    placeholder="test@example.com" value="test@example.com" />
      <input id="passwordInput" class="auth-input" type="password" placeholder="password"         value="password"        />
      <button class="btn btn-accent" onclick="login()">🔐 Sign In</button>
      <button class="btn btn-outline" onclick="logout()">Sign Out</button>
    </div>
    <div class="auth-status">
      <span class="auth-dot" id="authDot"></span>
      <span id="authStatus">Not signed in</span>
    </div>
  </div>

  <!-- Bug indicator (only shown when bugs are active - detected via API) -->
  <div class="bug-banner" id="bugBanner" style="display:none">
    <span>⚠️</span>
    <span id="bugText">Bug flags active — agents will detect these defects</span>
  </div>

  <!-- Products -->
  <h2 class="section-title">📦 Products</h2>
  <div class="products-grid" id="productsGrid">
    <div style="grid-column:1/-1;text-align:center;padding:40px;color:#9CA3AF">Loading products…</div>
  </div>

  <!-- Cart -->
  <div id="cartSection" style="display:none">
    <h2 class="section-title">🛒 Your Cart</h2>
    <div class="cart-section">
      <div id="cartItems"></div>
      <button class="btn btn-accent" onclick="checkout()" id="checkoutBtn" style="width:100%;padding:14px;font-size:15px">
        ✓ Place Order
      </button>
    </div>
  </div>

  <!-- Status bar -->
  <div class="status-bar">
    <div class="status-item">
      <div class="status-dot-sm" style="background:#22C55E"></div>
      <span>API: <strong id="apiStatus">checking…</strong></span>
    </div>
    <div class="status-item">
      <div class="status-dot-sm" style="background:#3B82F6"></div>
      <span>Auth: <span id="authStatusBar">unauthenticated</span></span>
    </div>
    <div class="status-item">
      <div class="status-dot-sm" style="background:#F59E0B"></div>
      <span>Orders this session: <span id="orderCount">0</span></span>
    </div>
    <div class="status-item" style="margin-left:auto">
      <span style="font-size:10px">TuskerSquad agent probe target</span>
    </div>
  </div>

</main>

<div id="toast">✅ Done</div>

<script>
const API = window.location.origin  // same-origin
let token = null
let cart  = {}   // {productId: {name, price, qty}}
let products = []
let orderCount = 0

// ── Toast ────────────────────────────────────────────────────────────────
function toast(msg, type = 'ok', duration = 3000) {
  const el = document.getElementById('toast')
  el.textContent = msg
  el.className = `show ${type}`
  clearTimeout(el._t)
  el._t = setTimeout(() => el.classList.remove('show'), duration)
}

// ── Auth ─────────────────────────────────────────────────────────────────
async function login() {
  const email    = document.getElementById('emailInput').value
  const password = document.getElementById('passwordInput').value
  try {
    const r = await fetch(`${API}/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    const data = await r.json()
    if (!r.ok) {
      toast(`❌ Login failed: ${data.detail || r.status}`, 'err')
      document.getElementById('authDot').className = 'auth-dot error'
      document.getElementById('authStatus').textContent = 'Login failed'
      document.getElementById('authStatusBar').textContent = 'failed'
      return
    }
    token = data.access_token
    document.getElementById('authDot').className = 'auth-dot ok'
    document.getElementById('authStatus').textContent = `Signed in as ${email}`
    document.getElementById('authStatusBar').textContent = email
    toast(`✅ Signed in as ${email}`)
  } catch (e) {
    toast(`❌ ${e.message}`, 'err')
  }
}

function logout() {
  token = null
  document.getElementById('authDot').className = 'auth-dot'
  document.getElementById('authStatus').textContent = 'Not signed in'
  document.getElementById('authStatusBar').textContent = 'unauthenticated'
  toast('Signed out', 'warn')
}

// ── Products ──────────────────────────────────────────────────────────────
async function loadProducts() {
  try {
    const r = await fetch(`${API}/products`)
    products = await r.json()
    renderProducts()
    document.getElementById('apiStatus').textContent = 'online'
  } catch (e) {
    document.getElementById('apiStatus').textContent = 'error'
    document.getElementById('productsGrid').innerHTML =
      `<div style="color:#EF4444;padding:20px">⚠ Could not load products: ${e.message}</div>`
  }
}

const PRODUCT_EMOJIS = { 'Laptop': '💻', 'Mouse': '🖱', 'Keyboard': '⌨️' }
const PRODUCT_DESCS  = {
  'Laptop':   'High-performance notebook for development',
  'Mouse':    'Ergonomic wireless mouse',
  'Keyboard': 'Mechanical keyboard — tactile switches',
}

function renderProducts() {
  const grid = document.getElementById('productsGrid')
  grid.innerHTML = products.map(p => `
    <div class="product-card" onclick="addToCart(${p.id}, '${p.name}', ${p.price})">
      <div class="product-img">${PRODUCT_EMOJIS[p.name] || '📦'}</div>
      <div class="product-body">
        <div class="product-name">${p.name}</div>
        <div style="font-size:12px;color:#6B7280;margin-bottom:10px">${PRODUCT_DESCS[p.name] || ''}</div>
        <div class="product-price"><span class="currency">$</span>${p.price.toFixed(2)}</div>
        <button class="add-btn">+ Add to Cart</button>
      </div>
    </div>
  `).join('')
}

// ── Cart ──────────────────────────────────────────────────────────────────
function addToCart(id, name, price) {
  if (!cart[id]) cart[id] = { name, price, qty: 0 }
  cart[id].qty += 1
  updateCartUI()
  toast(`Added ${name} to cart`)
}

function updateCartUI() {
  const items = Object.entries(cart).filter(([, v]) => v.qty > 0)
  const total = items.reduce((s, [, v]) => s + v.price * v.qty, 0)
  const count = items.reduce((s, [, v]) => s + v.qty, 0)

  document.getElementById('cartCount').textContent = count
  document.getElementById('cartSection').style.display = items.length ? '' : 'none'

  const cartEl = document.getElementById('cartItems')
  if (!items.length) {
    cartEl.innerHTML = '<div class="cart-empty">Cart is empty</div>'
    return
  }

  const EMOJIS = { 'Laptop': '💻', 'Mouse': '🖱', 'Keyboard': '⌨️' }
  cartEl.innerHTML = `
    <div class="cart-items">
      ${items.map(([id, v]) => `
        <div class="cart-item">
          <span class="cart-item-icon">${EMOJIS[v.name] || '📦'}</span>
          <span class="cart-item-name">${v.name}</span>
          <span class="cart-item-qty">× ${v.qty}</span>
          <span class="cart-item-price">$${(v.price * v.qty).toFixed(2)}</span>
          <button onclick="removeFromCart(${id})" style="background:none;border:none;cursor:pointer;color:#9CA3AF;font-size:16px;padding:0 4px">✕</button>
        </div>
      `).join('')}
    </div>
    <div class="cart-total">
      <span class="cart-total-label">Total</span>
      <span class="cart-total-amount">$${total.toFixed(2)}</span>
    </div>
  `
}

function removeFromCart(id) {
  delete cart[id]
  updateCartUI()
}

function toggleCart() {
  const sec = document.getElementById('cartSection')
  sec.style.display = sec.style.display === 'none' ? '' : 'none'
}

// ── Checkout ──────────────────────────────────────────────────────────────
async function checkout() {
  if (!token) {
    toast('⚠ Please sign in first', 'warn')
    return
  }
  const items = Object.entries(cart)
    .filter(([, v]) => v.qty > 0)
    .map(([id, v]) => ({ product_id: parseInt(id), quantity: v.qty }))
  if (!items.length) { toast('Cart is empty', 'warn'); return }

  const btn = document.getElementById('checkoutBtn')
  btn.textContent = '⏳ Processing…'
  btn.disabled = true

  try {
    const r = await fetch(`${API}/checkout`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({ items }),
    })
    const data = await r.json()
    if (!r.ok) {
      toast(`❌ Checkout failed: ${data.detail || r.status}`, 'err')
    } else {
      cart = {}
      orderCount++
      document.getElementById('orderCount').textContent = orderCount
      updateCartUI()
      toast(`✅ Order #${data.order_id} placed — Total: $${data.total.toFixed(2)}`)
    }
  } catch (e) {
    toast(`❌ Network error: ${e.message}`, 'err')
  } finally {
    btn.textContent = '✓ Place Order'
    btn.disabled = false
  }
}

// ── Health check + bug detection ──────────────────────────────────────────
async function checkHealth() {
  try {
    const r = await fetch(`${API}/health`)
    if (r.ok) document.getElementById('apiStatus').textContent = 'online'
  } catch {
    document.getElementById('apiStatus').textContent = 'offline'
  }
}

// ── Init ──────────────────────────────────────────────────────────────────
loadProducts()
checkHealth()
// Auto sign-in for demo convenience
setTimeout(login, 500)
</script>
</body>
</html>
"""

@router.get("/demo", response_class=HTMLResponse, include_in_schema=False)
def demo_ui():
    """Serves the demo storefront HTML."""
    return HTMLResponse(content=DEMO_HTML)


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def root():
    """Redirect root to demo UI."""
    return HTMLResponse(content='<meta http-equiv="refresh" content="0;url=/demo">')
