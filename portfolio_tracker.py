#!/usr/bin/env python3
"""
Garvit's Investment Portfolio Tracker
Fetches live prices for crypto + ETFs and generates a dashboard HTML file.
Run daily at 7 AM via scheduled task.
"""

import os, sys, json, subprocess, argparse
from datetime import datetime

# ── AUTO-INSTALL DEPS ────────────────────────────────────────
def pip(pkg):
    subprocess.check_call(
        [sys.executable, '-m', 'pip', 'install', pkg, '--break-system-packages', '-q'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

try:
    import requests
except ImportError:
    pip('requests'); import requests

try:
    import yfinance as yf
except ImportError:
    pip('yfinance'); import yfinance as yf

# ── HOLDINGS ─────────────────────────────────────────────────
CRYPTO = {
    'bitcoin':  {'symbol': 'BTC',  'name': 'Bitcoin',   'qty': 0.03737},
    'dogecoin': {'symbol': 'DOGE', 'name': 'Dogecoin',  'qty': 3367.22204},
}

ETFS = {
    'AGQ':  {'name': 'ProShares Ultra Silver',   'qty': 10.20},
    'TQQQ': {'name': 'ProShares UltraPro QQQ',   'qty': 70.43},
    'VOOG': {'name': 'Vanguard S&P 500 Growth',  'qty': 3.58},
    'VOO':  {'name': 'Vanguard S&P 500 ETF',     'qty': 10.27},
    'SMH':  {'name': 'VanEck Semiconductor ETF', 'qty': 72.78},
    'VGT':  {'name': 'Vanguard Info Tech ETF',   'qty': 12.02},
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── FETCH PRICES ─────────────────────────────────────────────
def fetch_crypto():
    ids = ','.join(CRYPTO.keys())
    url = (
        'https://api.coingecko.com/api/v3/simple/price'
        f'?ids={ids}&vs_currencies=usd&include_24hr_change=true'
    )
    try:
        return requests.get(url, timeout=15, headers={'User-Agent': 'portfolio-tracker/1.0'}).json()
    except Exception as e:
        print(f"[WARN] Crypto error: {e}", file=sys.stderr)
        return {}

def fetch_etfs():
    results = {}
    tickers = list(ETFS.keys())
    try:
        raw = yf.download(tickers, period='2d', progress=False, auto_adjust=True)
        closes = raw['Close']
        for t in tickers:
            try:
                col = closes[t] if t in closes.columns else None
                if col is None:
                    continue
                prices = col.dropna()
                curr = float(prices.iloc[-1])
                prev = float(prices.iloc[-2]) if len(prices) >= 2 else curr
                chg_pct = ((curr - prev) / prev * 100) if prev else 0
                results[t] = {
                    'price': curr, 'prev': prev,
                    'chg_pct': chg_pct, 'chg_usd': curr - prev
                }
            except Exception:
                pass
    except Exception as e:
        print(f"[WARN] ETF batch error: {e}", file=sys.stderr)
        # Fallback: fetch one by one
        for t in tickers:
            try:
                ticker = yf.Ticker(t)
                hist = ticker.history(period='2d')
                if hist.empty:
                    continue
                curr = float(hist['Close'].iloc[-1])
                prev = float(hist['Close'].iloc[-2]) if len(hist) >= 2 else curr
                chg_pct = ((curr - prev) / prev * 100) if prev else 0
                results[t] = {
                    'price': curr, 'prev': prev,
                    'chg_pct': chg_pct, 'chg_usd': curr - prev
                }
            except Exception as e2:
                print(f"[WARN] {t} error: {e2}", file=sys.stderr)
    return results

def fetch_news():
    """Fetch top headlines via Yahoo Finance RSS for key tickers."""
    news_items = []
    watch = ['VOO', 'TQQQ', 'BTC-USD', 'SMH']
    for sym in watch:
        try:
            url = f'https://feeds.finance.yahoo.com/rss/2.0/headline?s={sym}&region=US&lang=en-US'
            r = requests.get(url, timeout=8)
            import re
            titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', r.text)
            for t in titles[1:3]:   # skip first (feed title), take next 2
                news_items.append({'sym': sym, 'title': t.strip()})
        except Exception:
            pass
    return news_items[:6]  # cap at 6 items

# ── BUILD PORTFOLIO ───────────────────────────────────────────
def build_portfolio(crypto_data, etf_data):
    rows = []

    for cid, meta in CRYPTO.items():
        p = crypto_data.get(cid, {})
        price = p.get('usd', 0)
        chg_pct = p.get('usd_24h_change', 0)
        qty = meta['qty']
        value = price * qty
        chg_usd = value * chg_pct / 100
        rows.append({
            'name': meta['name'], 'symbol': meta['symbol'],
            'qty': qty, 'price': price, 'value': value,
            'chg_pct': chg_pct, 'chg_usd': chg_usd, 'type': 'Crypto'
        })

    for ticker, meta in ETFS.items():
        d = etf_data.get(ticker, {})
        price = d.get('price', 0)
        chg_pct = d.get('chg_pct', 0)
        qty = meta['qty']
        value = price * qty
        chg_usd = d.get('chg_usd', 0) * qty
        rows.append({
            'name': meta['name'], 'symbol': ticker,
            'qty': qty, 'price': price, 'value': value,
            'chg_pct': chg_pct, 'chg_usd': chg_usd, 'type': 'ETF'
        })

    total = sum(r['value'] for r in rows)
    total_chg = sum(r['chg_usd'] for r in rows)
    for r in rows:
        r['alloc'] = round(r['value'] / total * 100, 2) if total else 0
    rows.sort(key=lambda x: x['value'], reverse=True)
    return rows, total, total_chg

# ── HTML DASHBOARD ────────────────────────────────────────────
def generate_html(rows, total, total_chg, ts, news):
    prev_total = total - total_chg
    total_chg_pct = (total_chg / prev_total * 100) if prev_total else 0
    chg_color = '#22c55e' if total_chg >= 0 else '#ef4444'
    sign = '+' if total_chg >= 0 else ''
    top_gainer = max(rows, key=lambda x: x['chg_pct'])
    top_loser  = min(rows, key=lambda x: x['chg_pct'])

    crypto_val = sum(r['value'] for r in rows if r['type'] == 'Crypto')
    etf_val    = sum(r['value'] for r in rows if r['type'] == 'ETF')

    rows_html = ''
    for r in rows:
        c = '#22c55e' if r['chg_pct'] >= 0 else '#ef4444'
        s = '+' if r['chg_pct'] >= 0 else ''
        badge_bg = '#1e3a5f' if r['type'] == 'ETF' else '#2d1f4f'
        badge_color = '#60a5fa' if r['type'] == 'ETF' else '#a78bfa'
        rows_html += f'''
        <tr>
          <td style="padding:14px 16px 14px 24px">
            <strong style="color:#f1f5f9;font-size:15px">{r['symbol']}</strong>
            <div style="color:#64748b;font-size:12px;margin-top:2px">{r['name']}</div>
          </td>
          <td style="text-align:right;padding:14px 16px">
            <span style="background:{badge_bg};color:{badge_color};padding:3px 8px;border-radius:4px;font-size:11px;font-weight:600">{r['type']}</span>
          </td>
          <td style="text-align:right;padding:14px 16px;color:#cbd5e1">{r['qty']:,.4f}</td>
          <td style="text-align:right;padding:14px 16px;color:#cbd5e1">${r['price']:,.2f}</td>
          <td style="text-align:right;padding:14px 16px;color:#f1f5f9;font-weight:600">${r['value']:,.2f}</td>
          <td style="text-align:right;padding:14px 16px;color:{c};font-weight:600">{s}{r['chg_pct']:.2f}%</td>
          <td style="text-align:right;padding:14px 16px;color:{c}">{s}${abs(r['chg_usd']):,.2f}</td>
          <td style="text-align:right;padding:14px 16px;color:#94a3b8">{r['alloc']:.1f}%</td>
        </tr>'''

    news_html = ''
    for n in news:
        news_html += f'''
        <div style="padding:12px 0;border-bottom:1px solid #1e293b;display:flex;gap:12px;align-items:flex-start">
          <span style="background:#1e293b;color:#64748b;padding:2px 8px;border-radius:4px;font-size:11px;white-space:nowrap;margin-top:2px">{n['sym']}</span>
          <span style="color:#cbd5e1;font-size:14px;line-height:1.5">{n['title']}</span>
        </div>'''
    if not news_html:
        news_html = '<div style="color:#475569;font-size:14px;padding:16px 0">No recent headlines available.</div>'

    labels = json.dumps([r['symbol'] for r in rows])
    values = json.dumps([round(r['value'], 2) for r in rows])
    colors = json.dumps([
        '#3b82f6','#8b5cf6','#22c55e','#f59e0b',
        '#ef4444','#06b6d4','#ec4899','#14b8a6'
    ])

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Garvit's Portfolio — {ts}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#0f172a; color:#e2e8f0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; min-height:100vh; }}
  .container {{ max-width:1280px; margin:0 auto; padding:32px 24px; }}
  .header {{ margin-bottom:32px; display:flex; justify-content:space-between; align-items:flex-end; flex-wrap:wrap; gap:12px; }}
  .header h1 {{ font-size:30px; font-weight:800; color:#f8fafc; letter-spacing:-0.5px; }}
  .header-right {{ color:#475569; font-size:13px; text-align:right; }}
  .cards {{ display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:28px; }}
  .card {{ background:#1e293b; border:1px solid #334155; border-radius:14px; padding:22px; }}
  .card .label {{ color:#64748b; font-size:12px; text-transform:uppercase; letter-spacing:.06em; margin-bottom:10px; font-weight:600; }}
  .card .value {{ font-size:26px; font-weight:800; color:#f8fafc; letter-spacing:-0.5px; }}
  .card .sub {{ font-size:13px; margin-top:6px; }}
  .movers {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:28px; }}
  .mover {{ background:#1e293b; border-radius:14px; padding:22px; display:flex; align-items:center; gap:16px; }}
  .mover-badge {{ width:48px; height:48px; border-radius:12px; display:flex; align-items:center; justify-content:center; font-size:22px; flex-shrink:0; }}
  .mover-info .type {{ font-size:11px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; margin-bottom:4px; }}
  .mover-info .ticker {{ font-size:22px; font-weight:800; color:#f8fafc; }}
  .mover-info .fname {{ font-size:12px; color:#64748b; }}
  .mover-pct {{ margin-left:auto; font-size:28px; font-weight:800; }}
  .grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom:28px; }}
  .box {{ background:#1e293b; border:1px solid #334155; border-radius:14px; padding:24px; }}
  .box h2 {{ font-size:13px; color:#64748b; text-transform:uppercase; letter-spacing:.06em; font-weight:700; margin-bottom:20px; }}
  .table-box {{ background:#1e293b; border:1px solid #334155; border-radius:14px; overflow:hidden; margin-bottom:28px; }}
  .table-box-header {{ padding:22px 24px 0; display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; }}
  .table-box-header h2 {{ font-size:13px; color:#64748b; text-transform:uppercase; letter-spacing:.06em; font-weight:700; }}
  table {{ width:100%; border-collapse:collapse; }}
  th {{ background:#0f172a; color:#475569; font-size:11px; text-transform:uppercase; letter-spacing:.06em; padding:10px 16px; text-align:right; font-weight:600; }}
  th:first-child {{ text-align:left; padding-left:24px; }}
  td {{ border-top:1px solid #0f172a; font-size:14px; }}
  tr:hover td {{ background:#162032; }}
  .news-box {{ background:#1e293b; border:1px solid #334155; border-radius:14px; padding:24px; }}
  .news-box h2 {{ font-size:13px; color:#64748b; text-transform:uppercase; letter-spacing:.06em; font-weight:700; margin-bottom:16px; }}
  @media(max-width:900px) {{
    .cards {{ grid-template-columns:1fr 1fr; }}
    .grid2, .movers {{ grid-template-columns:1fr; }}
  }}
  @media(max-width:600px) {{
    .cards {{ grid-template-columns:1fr; }}
  }}
</style>
</head>
<body>
<div class="container">

  <div class="header">
    <div>
      <div style="color:#64748b;font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px">Investment Dashboard</div>
      <h1>Garvit's Portfolio</h1>
    </div>
    <div class="header-right">
      Updated: {ts}<br>
      Prices may be delayed up to 15 min
    </div>
  </div>

  <div class="cards">
    <div class="card">
      <div class="label">Total Value</div>
      <div class="value">${total:,.2f}</div>
      <div class="sub" style="color:{chg_color}">{sign}${abs(total_chg):,.2f} today</div>
    </div>
    <div class="card">
      <div class="label">Day's P&L</div>
      <div class="value" style="color:{chg_color}">{sign}${abs(total_chg):,.2f}</div>
      <div class="sub" style="color:{chg_color}">{sign}{total_chg_pct:.2f}% vs yesterday</div>
    </div>
    <div class="card">
      <div class="label">ETF Holdings</div>
      <div class="value" style="color:#3b82f6">${etf_val:,.2f}</div>
      <div class="sub" style="color:#475569">{sum(1 for r in rows if r['type']=='ETF')} positions</div>
    </div>
    <div class="card">
      <div class="label">Crypto Holdings</div>
      <div class="value" style="color:#8b5cf6">${crypto_val:,.2f}</div>
      <div class="sub" style="color:#475569">{sum(1 for r in rows if r['type']=='Crypto')} positions</div>
    </div>
  </div>

  <div class="movers">
    <div class="mover" style="border:1px solid #166534">
      <div class="mover-badge" style="background:#14532d">🚀</div>
      <div class="mover-info">
        <div class="type" style="color:#4ade80">Top Gainer</div>
        <div class="ticker">{top_gainer['symbol']}</div>
        <div class="fname">{top_gainer['name']}</div>
        <div style="color:#22c55e;font-size:13px;margin-top:4px">+${abs(top_gainer['chg_usd']):,.2f} total gain</div>
      </div>
      <div class="mover-pct" style="color:#22c55e">+{top_gainer['chg_pct']:.2f}%</div>
    </div>
    <div class="mover" style="border:1px solid #7f1d1d">
      <div class="mover-badge" style="background:#450a0a">📉</div>
      <div class="mover-info">
        <div class="type" style="color:#f87171">Top Loser</div>
        <div class="ticker">{top_loser['symbol']}</div>
        <div class="fname">{top_loser['name']}</div>
        <div style="color:#ef4444;font-size:13px;margin-top:4px">${top_loser['chg_usd']:,.2f} total loss</div>
      </div>
      <div class="mover-pct" style="color:#ef4444">{top_loser['chg_pct']:.2f}%</div>
    </div>
  </div>

  <div class="grid2">
    <div class="box">
      <h2>Portfolio Allocation</h2>
      <canvas id="pie" height="240"></canvas>
    </div>
    <div class="box">
      <h2>Holdings by Value (USD)</h2>
      <canvas id="bar" height="240"></canvas>
    </div>
  </div>

  <div class="table-box">
    <div class="table-box-header">
      <h2>All Holdings</h2>
      <span style="color:#475569;font-size:12px">{len(rows)} positions</span>
    </div>
    <table>
      <thead>
        <tr>
          <th style="text-align:left;padding-left:24px">Asset</th>
          <th>Type</th>
          <th>Quantity</th>
          <th>Price</th>
          <th>Value</th>
          <th>Day %</th>
          <th>Day $</th>
          <th>Allocation</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>

  <div class="news-box">
    <h2>Market Headlines</h2>
    {news_html}
  </div>

</div>
<script>
const labels = {labels};
const vals   = {values};
const colors = {colors};

new Chart(document.getElementById('pie'), {{
  type: 'doughnut',
  data: {{ labels, datasets: [{{ data: vals, backgroundColor: colors, borderColor: '#0f172a', borderWidth: 3 }}] }},
  options: {{
    plugins: {{
      legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 12 }}, padding: 16 }} }}
    }},
    cutout: '62%'
  }}
}});

new Chart(document.getElementById('bar'), {{
  type: 'bar',
  data: {{ labels, datasets: [{{ data: vals, backgroundColor: colors, borderRadius: 6 }}] }},
  options: {{
    indexAxis: 'y',
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{
        ticks: {{ color: '#64748b', callback: v => '$' + v.toLocaleString() }},
        grid: {{ color: '#1e293b' }}
      }},
      y: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#1e293b' }} }}
    }}
  }}
}});
</script>
</body>
</html>'''

# ── HTML EMAIL (Gmail-safe, white background) ─────────────────
def build_email_html(rows, total, total_chg, ts):
    prev = total - total_chg
    pct  = (total_chg / prev * 100) if prev else 0
    sign = '+' if total_chg >= 0 else ''
    chg_color = '#16a34a' if total_chg >= 0 else '#dc2626'
    gainer = max(rows, key=lambda x: x['chg_pct'])
    loser  = min(rows, key=lambda x: x['chg_pct'])

    rows_html = ''
    for r in rows:
        c = '#16a34a' if r['chg_pct'] >= 0 else '#dc2626'
        s = '+' if r['chg_pct'] >= 0 else ''
        rows_html += f'''
        <tr style="border-bottom:1px solid #f1f5f9">
          <td style="padding:10px 12px;font-weight:700;color:#1e293b;font-size:14px">{r['symbol']}</td>
          <td style="padding:10px 12px;color:#64748b;font-size:13px">{r['name']}</td>
          <td style="padding:10px 12px;text-align:right;font-weight:700;color:#0f172a;font-size:14px">${r['value']:,.0f}</td>
          <td style="padding:10px 12px;text-align:right;font-weight:700;color:{c};font-size:14px">{s}{r['chg_pct']:.2f}%</td>
          <td style="padding:10px 12px;text-align:right;color:#94a3b8;font-size:13px">{r['alloc']:.1f}%</td>
        </tr>'''

    return f'''<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif">
<div style="max-width:600px;margin:0 auto;padding:24px 16px">

  <!-- Header -->
  <div style="margin-bottom:20px">
    <div style="color:#94a3b8;font-size:11px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px">Investment Dashboard</div>
    <h1 style="color:#0f172a;font-size:22px;font-weight:800;margin:0 0 4px">Garvit's Portfolio</h1>
    <div style="color:#64748b;font-size:12px">{ts}</div>
  </div>

  <!-- Total + P&L cards -->
  <table style="width:100%;border-collapse:collapse;margin-bottom:16px">
    <tr>
      <td style="background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;padding:18px;width:47%;vertical-align:top">
        <div style="color:#64748b;font-size:10px;text-transform:uppercase;font-weight:700;margin-bottom:6px">Total Value</div>
        <div style="font-size:28px;font-weight:800;color:#0f172a">${total:,.2f}</div>
      </td>
      <td style="width:6%"></td>
      <td style="background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;padding:18px;width:47%;vertical-align:top">
        <div style="color:#64748b;font-size:10px;text-transform:uppercase;font-weight:700;margin-bottom:6px">Day's P&amp;L</div>
        <div style="font-size:28px;font-weight:800;color:{chg_color}">{sign}${abs(total_chg):,.2f}</div>
        <div style="color:{chg_color};font-size:13px;margin-top:4px">{sign}{pct:.2f}% vs yesterday</div>
      </td>
    </tr>
  </table>

  <!-- Gainer + Loser -->
  <table style="width:100%;border-collapse:collapse;margin-bottom:16px">
    <tr>
      <td style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:14px 16px;width:47%;vertical-align:top">
        <div style="color:#15803d;font-size:10px;font-weight:800;text-transform:uppercase;margin-bottom:4px">Top Gainer</div>
        <div style="font-size:20px;font-weight:800;color:#0f172a">{gainer['symbol']}</div>
        <div style="color:#64748b;font-size:12px">{gainer['name']}</div>
        <div style="color:#16a34a;font-size:18px;font-weight:800;margin-top:4px">+{gainer['chg_pct']:.2f}%</div>
      </td>
      <td style="width:6%"></td>
      <td style="background:#fef2f2;border:1px solid #fecaca;border-radius:10px;padding:14px 16px;width:47%;vertical-align:top">
        <div style="color:#b91c1c;font-size:10px;font-weight:800;text-transform:uppercase;margin-bottom:4px">Top Loser</div>
        <div style="font-size:20px;font-weight:800;color:#0f172a">{loser['symbol']}</div>
        <div style="color:#64748b;font-size:12px">{loser['name']}</div>
        <div style="color:#dc2626;font-size:18px;font-weight:800;margin-top:4px">{loser['chg_pct']:.2f}%</div>
      </td>
    </tr>
  </table>

  <!-- Holdings table -->
  <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden;margin-bottom:16px">
    <div style="padding:16px 16px 0;margin-bottom:12px">
      <div style="color:#64748b;font-size:10px;text-transform:uppercase;font-weight:700">All Holdings</div>
    </div>
    <table style="width:100%;border-collapse:collapse">
      <thead>
        <tr style="background:#f8fafc">
          <th style="text-align:left;padding:8px 12px;color:#94a3b8;font-size:10px;font-weight:700;text-transform:uppercase">Symbol</th>
          <th style="text-align:left;padding:8px 12px;color:#94a3b8;font-size:10px;font-weight:700;text-transform:uppercase">Name</th>
          <th style="text-align:right;padding:8px 12px;color:#94a3b8;font-size:10px;font-weight:700;text-transform:uppercase">Value</th>
          <th style="text-align:right;padding:8px 12px;color:#94a3b8;font-size:10px;font-weight:700;text-transform:uppercase">Day %</th>
          <th style="text-align:right;padding:8px 12px;color:#94a3b8;font-size:10px;font-weight:700;text-transform:uppercase">Alloc</th>
        </tr>
      </thead>
      <tbody>{rows_html}
      </tbody>
    </table>
  </div>

  <!-- Footer -->
  <div style="color:#94a3b8;font-size:11px;text-align:center;padding-top:8px">
    Garvit's Portfolio Tracker &mdash; Automated daily at 7:00 AM
  </div>
</div>
</body></html>'''


# ── SEND EMAIL ────────────────────────────────────────────────
def send_email(html_body, subject, config_path):
    """Send HTML email via Gmail SMTP using App Password stored in config."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    if not os.path.exists(config_path):
        print(f"[SKIP] No email config found at {config_path}", file=sys.stderr)
        return False

    with open(config_path) as f:
        cfg = json.load(f)

    smtp_user = cfg.get('smtp_user', '')
    smtp_pass = cfg.get('smtp_pass', '')
    to_addr   = cfg.get('to', smtp_user)

    if not smtp_pass or smtp_pass == 'YOUR_APP_PASSWORD_HERE':
        print("[SKIP] App password not set in email_config.json", file=sys.stderr)
        return False

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From']    = smtp_user
    msg['To']      = to_addr
    msg.attach(MIMEText(html_body, 'html'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to_addr, msg.as_string())
        print(f"[OK] Email sent to {to_addr}", file=sys.stderr)
        return True
    except Exception as e:
        print(f"[ERROR] Email failed: {e}", file=sys.stderr)
        return False


# ── PLAIN-TEXT SUMMARY ────────────────────────────────────────
def build_summary(rows, total, total_chg, ts):
    prev = total - total_chg
    pct = (total_chg / prev * 100) if prev else 0
    sign = '+' if total_chg >= 0 else ''
    gainer = max(rows, key=lambda x: x['chg_pct'])
    loser  = min(rows, key=lambda x: x['chg_pct'])

    lines = [
        f"PORTFOLIO SUMMARY — {ts}",
        f"{'='*50}",
        f"Total Value:   ${total:,.2f}",
        f"Day's P&L:     {sign}${total_chg:,.2f} ({sign}{pct:.2f}%)",
        f"",
        f"TOP GAINER:  {gainer['symbol']}  +{gainer['chg_pct']:.2f}%  (+${abs(gainer['chg_usd']):,.2f})",
        f"TOP LOSER:   {loser['symbol']}   {loser['chg_pct']:.2f}%  (-${abs(loser['chg_usd']):,.2f})",
        f"",
        f"HOLDINGS:",
        f"{'─'*50}",
    ]
    for r in rows:
        s = '+' if r['chg_pct'] >= 0 else ''
        lines.append(
            f"  {r['symbol']:<6}  ${r['value']:>10,.2f}  {s}{r['chg_pct']:>6.2f}%  Alloc {r['alloc']:.1f}%"
        )

    return '\n'.join(lines)

# ── LOAD PRE-FETCHED PRICES (browser mode) ───────────────────
def load_prefetched(path):
    """
    Load prices from a JSON file written by the browser-fetch step.
    Expected format:
    {
      "crypto": {
        "bitcoin":  {"usd": 83000.0, "usd_24h_change": 1.23},
        "dogecoin": {"usd": 0.18,    "usd_24h_change": -0.5}
      },
      "etfs": {
        "AGQ":  {"price": 52.10, "prev": 51.80, "chg_pct": 0.58, "chg_usd": 0.30},
        ...
      }
    }
    """
    with open(path) as f:
        data = json.load(f)
    return data.get('crypto', {}), data.get('etfs', {})

# ── MAIN ──────────────────────────────────────────────────────
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prices-file', default=None,
                        help='Path to pre-fetched prices JSON (skips live API calls)')
    args = parser.parse_args()

    ts = datetime.now().strftime('%B %d, %Y at %I:%M %p')

    if args.prices_file:
        print(f"Loading pre-fetched prices from {args.prices_file}", file=sys.stderr)
        crypto_data, etf_data = load_prefetched(args.prices_file)
        news = []
    else:
        print("Fetching crypto prices...", file=sys.stderr)
        crypto_data = fetch_crypto()

        print("Fetching ETF prices...", file=sys.stderr)
        etf_data = fetch_etfs()

        print("Fetching news...", file=sys.stderr)
        news = fetch_news()

    rows, total, total_chg = build_portfolio(crypto_data, etf_data)

    # Save HTML dashboard
    html = generate_html(rows, total, total_chg, ts, news)
    html_path = os.path.join(SCRIPT_DIR, 'portfolio_dashboard.html')
    with open(html_path, 'w') as f:
        f.write(html)
    print(f"Dashboard saved: {html_path}", file=sys.stderr)

    # Send HTML email
    email_html   = build_email_html(rows, total, total_chg, ts)
    config_path  = os.path.join(SCRIPT_DIR, 'email_config.json')
    send_email(email_html, 'Daily Portfolio Summary from Claude', config_path)

    # Print plain-text summary
    summary = build_summary(rows, total, total_chg, ts)
    print(summary)

    # Also write JSON for programmatic use
    prev = total - total_chg
    result = {
        'timestamp': ts,
        'total_value': round(total, 2),
        'total_day_change': round(total_chg, 2),
        'total_day_change_pct': round((total_chg / prev * 100) if prev else 0, 2),
        'top_gainer': {'symbol': max(rows, key=lambda x: x['chg_pct'])['symbol'],
                       'pct': round(max(rows, key=lambda x: x['chg_pct'])['chg_pct'], 2)},
        'top_loser':  {'symbol': min(rows, key=lambda x: x['chg_pct'])['symbol'],
                       'pct': round(min(rows, key=lambda x: x['chg_pct'])['chg_pct'], 2)},
        'holdings': [{'symbol': r['symbol'], 'value': round(r['value'], 2),
                      'chg_pct': round(r['chg_pct'], 2)} for r in rows],
        'html_path': html_path,
    }
    json_path = os.path.join(SCRIPT_DIR, 'portfolio_latest.json')
    with open(json_path, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"JSON saved: {json_path}", file=sys.stderr)
