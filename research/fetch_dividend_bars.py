"""Cache daily bars for the dividend portfolio's US symbols under research/data/bars_div/<SYM>.csv
(same paging as fetch_bars.py; 3 pages x 600 bars ~ 7y). Respects Tiger's 60 kline calls/min."""
import os, sys, time
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from tiger_client import get_client_config
from tigeropen.quote.quote_client import QuoteClient
from tigeropen.common.consts import BarPeriod
from portfolio_profiles import DIVIDEND_PROFILE, effective_universe

OUT = os.path.join(os.path.dirname(__file__), 'data', 'bars_div')
os.makedirs(OUT, exist_ok=True)
qc = QuoteClient(get_client_config())
for s in [e.symbol for e in effective_universe(DIVIDEND_PROFILE) if e.market == 'US']:
    path = os.path.join(OUT, f'{s}.csv')
    if os.path.exists(path) and '--refresh' not in sys.argv:
        continue
    frames, end = [], None
    for _ in range(3):
        kw = dict(period=BarPeriod.DAY, limit=600)
        if end: kw['end_time'] = end
        df = qc.get_bars([s], **kw)
        time.sleep(1.2)
        if df is None or len(df) == 0: break
        frames.append(df)
        end = int(df['time'].min()) - 1
        if len(df) < 600: break
    df = pd.concat(frames).drop_duplicates('time').sort_values('time')
    df['date'] = pd.to_datetime(df['time'], unit='ms', utc=True).dt.tz_convert('America/New_York').dt.date
    df[['date', 'open', 'high', 'low', 'close', 'volume']].to_csv(path, index=False)
    print(s, len(df), df['date'].iloc[0], df['date'].iloc[-1])
