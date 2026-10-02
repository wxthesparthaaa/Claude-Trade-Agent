"""Cache daily OHLC bars for the US growth universe under research/data/bars/<SYM>.csv.
Respects Tiger's 60 kline-calls/min limit (1.2s between calls). Re-run is a no-op for cached symbols
unless --refresh is passed. Pages backwards with end_time to get ~5y of history."""
import os, sys, time
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from tiger_client import get_client_config
from tigeropen.quote.quote_client import QuoteClient
from tigeropen.common.consts import BarPeriod
from portfolio_profiles import GROWTH_PROFILE, effective_universe

OUT = os.path.join(os.path.dirname(__file__), 'data', 'bars')
refresh = '--refresh' in sys.argv
qc = QuoteClient(get_client_config())
syms = [e.symbol for e in effective_universe(GROWTH_PROFILE) if e.market == 'US'] + ['SPY']
for s in syms:
    path = os.path.join(OUT, f'{s}.csv')
    if os.path.exists(path) and not refresh:
        continue
    frames, end = [], None
    for _ in range(3):  # 3 pages x 600 bars
        kw = dict(period=BarPeriod.DAY, limit=600)
        if end: kw['end_time'] = end
        try:
            df = qc.get_bars([s], **kw)
        except Exception as e:
            print(s, 'ERR', e); time.sleep(5); break
        time.sleep(1.2)
        if df is None or len(df) == 0: break
        frames.append(df)
        new_end = int(df['time'].min()) - 1
        if end is not None and new_end >= end: break
        end = new_end
        if len(df) < 600: break
    if frames:
        df = pd.concat(frames).drop_duplicates('time').sort_values('time')
        df['date'] = pd.to_datetime(df['time'], unit='ms', utc=True).dt.tz_convert('America/New_York').dt.date
        df[['date', 'open', 'high', 'low', 'close', 'volume']].to_csv(path, index=False)
        print(s, len(df), df['date'].iloc[0], df['date'].iloc[-1])
