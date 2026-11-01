"""Cache historical US earnings dates (Tiger corporate earnings calendar) for the research universe under
research/data/earnings.csv. One call per week, ~1.2 s apart. Columns kept: symbol, report_date, report_time, expected_eps, actual_eps (consensus vs reported, for the surprise signal)."""
import os, sys, time, glob
from datetime import date, timedelta
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from tiger_client import get_client_config
from tigeropen.quote.quote_client import QuoteClient
from tigeropen.common.consts import Market

HERE = os.path.dirname(__file__)
syms = {os.path.basename(p)[:-4] for p in glob.glob(os.path.join(HERE, 'data', 'bars', '*.csv'))}
syms |= {os.path.basename(p)[:-4] for p in glob.glob(os.path.join(HERE, 'data', 'bars_div', '*.csv'))}
qc = QuoteClient(get_client_config())
out, d, end = [], date(2019, 8, 1), date(2026, 11, 20)
while d < end:
    e = d + timedelta(days=6)
    try:
        df = qc.get_corporate_earnings_calendar(market=Market.US, begin_date=d.isoformat(), end_date=e.isoformat())
        if df is not None and len(df):
            out.append(df[df['symbol'].isin(syms)][['symbol', 'report_date', 'report_time', 'expected_eps', 'actual_eps']])
    except Exception as ex:
        print(d, 'ERR', str(ex).encode('ascii', 'replace').decode()[:100]); time.sleep(5)
    time.sleep(1.2)
    d = e + timedelta(days=1)
res = pd.concat(out).drop_duplicates(['symbol', 'report_date']).sort_values(['symbol', 'report_date'])
res.to_csv(os.path.join(HERE, 'data', 'earnings.csv'), index=False)
print(len(res), 'earnings rows;', res['symbol'].nunique(), 'symbols;', res['report_date'].min(), '->', res['report_date'].max())
