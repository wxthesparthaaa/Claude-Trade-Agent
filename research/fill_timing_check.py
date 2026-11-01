"""Do our 09:35 ET market-order fills pay a premium vs a calmer price ~30 min later?
Inspired by day-trader-skill's rule of not entering in the first 15 minutes. Real Tiger fills (growth + dividend
symbols) vs 5-minute bars. shortfall > 0 = we did WORSE than the later reference (buy higher / sell lower)."""
import os, sys, time, statistics as st
from collections import defaultdict
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from tiger_client import get_client_config
from tigeropen.trade.trade_client import TradeClient
from tigeropen.quote.quote_client import QuoteClient
from tigeropen.common.consts import BarPeriod
NY = ZoneInfo('America/New_York')
cfg = get_client_config(); tc, qc = TradeClient(cfg), QuoteClient(cfg)
orders = tc.get_filled_orders(start_time=(date.today() - timedelta(days=60)).isoformat(), end_time=(date.today() + timedelta(days=1)).isoformat())
fills = []
for o in orders:
    t = datetime.fromtimestamp(o.trade_time / 1000, NY)
    if (t.hour, t.minute) < (9, 30) or (t.hour, t.minute) > (9, 45) or not o.filled: continue   # only the open-scan fills
    fills.append((o.contract.symbol, o.action, o.avg_fill_price, o.filled, t, o.commission or 0.0))
print('open-window fills:', len(fills))
bars_cache = {}
def day_bars(sym, d):
    k = (sym, d)
    if k not in bars_cache:
        b = datetime(d.year, d.month, d.day, 9, 30, tzinfo=NY); e = datetime(d.year, d.month, d.day, 11, 0, tzinfo=NY)
        try:
            df = qc.get_bars([sym], period=BarPeriod.FIVE_MINUTES, begin_time=int(b.timestamp() * 1000), end_time=int(e.timestamp() * 1000), limit=30)
        except Exception as ex:
            df = None; print(sym, d, 'ERR', str(ex)[:60])
        time.sleep(1.1); bars_cache[k] = df
    return bars_cache[k]
rows = []
for sym, act, px, qty, t, comm in fills:
    df = day_bars(sym, t.date())
    if df is None or len(df) < 8: continue
    df = df.copy(); df['dt'] = [datetime.fromtimestamp(x / 1000, NY) for x in df['time']]
    later = df[(df['dt'].dt.hour == 10) & (df['dt'].dt.minute < 30)]
    if len(later) < 3: continue
    vwap = (later['close'] * later['volume']).sum() / later['volume'].sum()
    sign = 1 if act == 'BUY' else -1
    sf = sign * (px - vwap) / vwap
    first = df[(df['dt'].dt.hour == 9) & (df['dt'].dt.minute <= 40)]
    rng_open = ((first['high'] - first['low']) / first['close']).mean(); rng_later = ((later['high'] - later['low']) / later['close']).mean()
    rows.append((sym, act, px * qty, sf, comm / (px * qty), rng_open, rng_later))
n = len(rows)
print('fills measured:', n)
sfs = [r[3] * 100 for r in rows]
print(f"mean shortfall vs 10:00-10:30 VWAP: {st.mean(sfs):+.3f}%  (median {st.median(sfs):+.3f}%, s.e. {st.pstdev(sfs)/n**.5:.3f}%)")
for a in ('BUY', 'SELL'):
    x = [r[3] * 100 for r in rows if r[1] == a]
    if x: print(f"  {a}: n={len(x)} mean {st.mean(x):+.3f}%")
print(f"avg commission as % of notional: {st.mean(r[4] for r in rows)*100:.2f}%   (notional-weighted: {sum(r[4]*r[2] for r in rows)/sum(r[2] for r in rows)*100:.2f}%)")
print(f"avg 5-min range, 09:30-09:40: {st.mean(r[5] for r in rows)*100:.2f}%  vs 10:00-10:30: {st.mean(r[6] for r in rows)*100:.2f}%")
