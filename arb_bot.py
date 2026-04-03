#!/usr/bin/env python3
"""
◈ STABLE·ARB — Bot Telegram para GitHub Actions
Corre una vez, chequea spreads, manda alerta si hay oportunidad y termina.
GitHub Actions lo ejecuta cada 5 minutos automáticamente.
"""

import os
import json
import requests
from datetime import datetime

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

THRESHOLDS = {
    "USDC": 0.25,
    "DAI":  0.25,
    "BTC":  0.30,
    "ETH":  0.30,
    "SOL":  0.40,
    "XRP":  0.40,
    "BNB":  0.40,
}

FEES_ROUNDTRIP = 0.20

PAIRS = {
    "USDC": {"Binance": "USDCUSDT", "Kraken": "USDCUSD",  "KuCoin": "USDC-USDT", "Bybit": "USDCUSDT"},
    "DAI":  {"Binance": "DAIUSDT",  "Kraken": "DAIUSD",   "KuCoin": "DAI-USDT",  "Bybit": "DAIUSDT"},
    "BTC":  {"Binance": "BTCUSDT",  "Kraken": "XBTUSD",   "KuCoin": "BTC-USDT",  "Bybit": "BTCUSDT"},
    "ETH":  {"Binance": "ETHUSDT",  "Kraken": "ETHUSD",   "KuCoin": "ETH-USDT",  "Bybit": "ETHUSDT"},
    "SOL":  {"Binance": "SOLUSDT",  "Kraken": "SOLUSD",   "KuCoin": "SOL-USDT",  "Bybit": "SOLUSDT"},
    "XRP":  {"Binance": "XRPUSDT",  "Kraken": "XRPUSD",   "KuCoin": "XRP-USDT",  "Bybit": "XRPUSDT"},
    "BNB":  {"Binance": "BNBUSDT",  "Kraken": None,        "KuCoin": "BNB-USDT",  "Bybit": "BNBUSDT"},
}

def fetch_binance():
    try:
        symbols = [v["Binance"] for v in PAIRS.values() if v.get("Binance")]
        r = requests.get(f'https://api.binance.com/api/v3/ticker/price?symbols={json.dumps(symbols)}', timeout=8)
        sym_map = {i["symbol"]: float(i["price"]) for i in r.json()}
        return {p: sym_map[c["Binance"]] for p, c in PAIRS.items() if c.get("Binance") and c["Binance"] in sym_map}
    except Exception as e:
        print(f"Binance error: {e}"); return {}

def fetch_kraken():
    try:
        pairs = [v["Kraken"] for v in PAIRS.values() if v.get("Kraken")]
        r = requests.get(f'https://api.kraken.com/0/public/Ticker?pair={",".join(pairs)}', timeout=8)
        data = r.json()
        if data.get("error"): return {}
        result = {}
        for pair, cfg in PAIRS.items():
            sym = cfg.get("Kraken")
            if not sym: continue
            match = next((k for k in data["result"]
                          if sym in k or k == sym.replace("XBT","XXBT").replace("USD","ZUSD")), None)
            if match:
                result[pair] = float(data["result"][match]["c"][0])
        return result
    except Exception as e:
        print(f"Kraken error: {e}"); return {}

def fetch_kucoin():
    result = {}
    for pair, cfg in PAIRS.items():
        sym = cfg.get("KuCoin")
        if not sym: continue
        try:
            r = requests.get(f'https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={sym}', timeout=6)
            d = r.json()
            if d.get("code") == "200000" and d.get("data", {}).get("price"):
                result[pair] = float(d["data"]["price"])
        except: pass
    return result

def fetch_bybit():
    try:
        r = requests.get('https://api.bybit.com/v5/market/tickers?category=spot', timeout=8)
        data = r.json()
        if data.get("retCode") != 0: return {}
        sym_map = {i["symbol"]: float(i["lastPrice"]) for i in data["result"]["list"]}
        return {p: sym_map[c["Bybit"]] for p, c in PAIRS.items() if c.get("Bybit") and c["Bybit"] in sym_map}
    except Exception as e:
        print(f"Bybit error: {e}"); return {}

def fetch_all():
    b, k, ku, by = fetch_binance(), fetch_kraken(), fetch_kucoin(), fetch_bybit()
    all_data = {pair: {} for pair in PAIRS}
    for pair in PAIRS:
        if pair in b:  all_data[pair]["Binance"] = b[pair]
        if pair in k:  all_data[pair]["Kraken"]  = k[pair]
        if pair in ku: all_data[pair]["KuCoin"]  = ku[pair]
        if pair in by: all_data[pair]["Bybit"]   = by[pair]
    return all_data

def find_opportunities(all_data):
    opps = []
    for pair, exchanges in all_data.items():
        if len(exchanges) < 2: continue
        prices = sorted(exchanges.items(), key=lambda x: x[1])
        lo_ex, lo = prices[0]
        hi_ex, hi = prices[-1]
        gross = (hi - lo) / lo * 100
        net   = gross - FEES_ROUNDTRIP
        if gross >= THRESHOLDS.get(pair, 0.30):
            opps.append({"pair": pair, "buy_ex": lo_ex, "buy_price": lo,
                         "sell_ex": hi_ex, "sell_price": hi,
                         "gross": gross, "net": net, "profitable": net > 0})
    return sorted(opps, key=lambda x: x["gross"], reverse=True)

def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Sin credenciales de Telegram."); return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=8
        )
        return r.status_code == 200
    except Exception as e:
        print(f"Telegram error: {e}"); return False

def format_message(opps):
    now   = datetime.utcnow().strftime("%H:%M UTC")
    lines = []
    for opp in opps:
        emoji      = "🔥" if opp["gross"] > 0.80 else "✅" if opp["net"] > 0 else "⚠️"
        dec        = 6 if opp["pair"] in ("USDC","DAI","XRP") else 2
        net_str    = f"+{opp['net']:.4f}%" if opp["net"] >= 0 else f"{opp['net']:.4f}%"
        profit_1k  = opp["net"] / 100 * 1000
        profit_str = f"+${profit_1k:.2f}" if profit_1k >= 0 else f"-${abs(profit_1k):.2f}"
        lines.append(
            f"{emoji} <b>{opp['pair']}/USD</b> — spread {opp['gross']:.4f}%\n"
            f"   📗 Comprar {opp['buy_ex']}  <code>${opp['buy_price']:.{dec}f}</code>\n"
            f"   📕 Vender  {opp['sell_ex']}  <code>${opp['sell_price']:.{dec}f}</code>\n"
            f"   💰 Neto: {net_str} → <b>{profit_str} por $1,000</b>"
        )
    return (
        f"◈ <b>STABLE·ARB — {len(opps)} oportunidad{'es' if len(opps)>1 else ''}</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"\n\n".join(lines) + "\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🕐 {now}"
    )

def main():
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Chequeando precios...")
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID"); exit(1)

    all_data = fetch_all()
    active = [ex for ex in ["Binance","Kraken","KuCoin","Bybit"]
              if any(ex in d for d in all_data.values())]
    print(f"Exchanges: {', '.join(active) or 'ninguno'}")

    opps = find_opportunities(all_data)
    print(f"Oportunidades: {len(opps)}")

    if opps:
        for o in opps:
            print(f"  {'🔥' if o['gross']>0.8 else '✅' if o['net']>0 else '⚠️'} "
                  f"{o['pair']}: {o['gross']:.4f}% ({o['buy_ex']}→{o['sell_ex']})")
        if send_telegram(format_message(opps)):
            print("✓ Mensaje enviado.")
        else:
            print("✗ Error al enviar.")
    else:
        print("Sin spreads sobre umbral. Sin mensaje.")

if __name__ == "__main__":
    main()
