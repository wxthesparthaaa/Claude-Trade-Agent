"""Fetch a large-cap daily panel (2000-today, split/dividend-adjusted close) from the Yahoo chart API to build PROXY market breadth.
Official NYSE/Nasdaq advance-decline and new-high/low history is paywalled, so breadth is computed from this panel instead.
Caveat: today's survivors only (survivorship bias flatters old washouts' breadth). Usage: python research/fetch_breadth_panel.py"""
import os, json, time, urllib.request, urllib.parse
import pandas as pd
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'breadth')
os.makedirs(OUT, exist_ok=True)
T = """AAPL MSFT AMZN GOOGL NVDA META TSLA AVGO ORCL ADBE CRM CSCO INTC AMD QCOM TXN IBM MU AMAT LRCX KLAC ADI NXPI MCHP
JPM BAC WFC C GS MS AXP USB PNC SCHW BLK MET AIG CB TRV ALL PGR V MA
JNJ PFE MRK ABT LLY BMY AMGN GILD UNH CVS CI MDT TMO DHR ISRG BDX SYK ZTS
XOM CVX COP SLB EOG OXY PSX VLO MPC HAL
WMT COST HD LOW TGT NKE MCD SBUX KO PEP PG CL KMB MDLZ MO PM DIS CMCSA T VZ
CAT DE HON GE MMM UPS FDX LMT RTX BA UNP CSX NSC EMR ITW
NEE DUK SO D AEP EXC LIN APD SHW ECL NEM FCX DOW
F GM AMT PLD SPG EQIX O WM ROST TJX BKNG ADP INTU PAYX""".split()
def fetch(s):
    u = 'https://query1.finance.yahoo.com/v8/finance/chart/%s?period1=946684800&period2=%d&interval=1d&events=div,split' % (urllib.parse.quote(s), time.time())
    j = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30).read())
    r = j['chart']['result'][0]
    adj = r['indicators']['adjclose'][0]['adjclose']
    return pd.Series(adj, index=pd.to_datetime(r['timestamp'], unit='s').normalize(), name=s)
cols, bad = {}, []
for s in dict.fromkeys(T):
    try:
        cols[s] = fetch(s)
    except Exception as e:
        bad.append((s, str(e)[:40]))
    time.sleep(0.15)
df = pd.DataFrame(cols).sort_index()
df = df[~df.index.duplicated()]
df.to_csv(os.path.join(OUT, 'panel_adjclose.csv'), index_label='date')
print(df.shape, df.index[0].date(), df.index[-1].date(), 'failed:', bad)
