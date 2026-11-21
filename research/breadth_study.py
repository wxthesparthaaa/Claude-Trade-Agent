"""Do the TradingView McClellan Oscillator (<-80) and High-Low Index (10d SMA < 5) washout signals work?  (2026-11-21)
Official breadth history is paywalled, so breadth is rebuilt from a 133-large-cap panel (fetch_breadth_panel.py): advancers/
decliners from daily moves, new highs/lows = close at its 252-day high/low. PROXY: today's survivors, large caps only.
Forward returns are on the S&P 500 price index (research/data/index/GSPC.csv). Usage: python research/breadth_study.py"""
import os
import numpy as np, pandas as pd
R = os.path.dirname(os.path.abspath(__file__))
P = pd.read_csv(os.path.join(R, 'data', 'breadth', 'panel_adjclose.csv'), parse_dates=['date']).set_index('date')
sp = pd.read_csv(os.path.join(R, 'data', 'index', 'GSPC.csv'), parse_dates=['date']).set_index('date')['close']
vix = pd.read_csv(os.path.join(R, 'data', 'index', 'VIX.csv'), parse_dates=['date']).set_index('date')['close']

# --- breadth (same formulas as the two scripts) ---
chg = P.diff()
valid = P.notna() & P.shift(1).notna()
adv = ((chg > 0) & valid).sum(axis=1); dec = ((chg < 0) & valid).sum(axis=1)
ana = (adv - dec) / (adv + dec).replace(0, np.nan) * 1000
osc = ana.ewm(span=19, adjust=False).mean() - ana.ewm(span=39, adjust=False).mean()
hi = (P >= P.rolling(252, min_periods=252).max()).sum(axis=1); lo = (P <= P.rolling(252, min_periods=252).min()).sum(axis=1)
hli = (hi / (hi + lo).replace(0, np.nan) * 100)
hlima = hli.ffill().rolling(10).mean()          # the script's 10-day SMA; days with no highs/lows carry the last value

idx = sp.loc['2001-06-01':].index
px = sp.reindex(idx).values; dates = idx; n = len(px)
osc = osc.reindex(idx); hlima = hlima.reindex(idx); hli = hli.reindex(idx)
ath = np.maximum.accumulate(sp.loc['1950-01-01':].values)[-n:]
dd = px / ath - 1
v = vix.reindex(idx).ffill().values
ma200 = sp.rolling(200).mean().reindex(idx).values

print(f'panel: {P.shape[1]} stocks, {P.index[0].date()}..{P.index[-1].date()}; testing S&P 2001-06..{dates[-1].date()}')
print(f'osc percentiles 1/5/10/50/90: ' + ' '.join(f'{osc.quantile(q):.0f}' for q in (.01, .05, .10, .5, .9)) + f' | days osc<-80: {(osc<-80).mean()*100:.1f}%  <-100: {(osc<-100).mean()*100:.1f}%')
print(f'hlima percentiles 1/5/10/50/90: ' + ' '.join(f'{hlima.quantile(q):.1f}' for q in (.01, .05, .10, .5, .9)) + f' | days hlima<5: {(hlima<5).mean()*100:.1f}%  <10: {(hlima<10).mean()*100:.1f}%')


def events(cond, quiet=63):
    c = np.asarray(cond, dtype=bool); out, last = [], -10 ** 9
    for i in range(n):
        if c[i] and i - last > quiet:
            out.append(i)
        if c[i]:
            last = i
    return out


def row(name, ev):
    f = lambda h: np.array([px[i + h] / px[i] - 1 for i in ev if i + h < n])
    f1, f3, f12 = f(21), f(63), f(252)
    fall = np.array([px[i:min(i + 126, n)].min() / px[i] - 1 for i in ev])
    if not len(ev):
        print(f'{name:>40} n=0'); return
    print(f"{name:>40} {len(ev):>3} | 1m {np.median(f1)*100:+5.1f}% | 3m {np.median(f3)*100:+5.1f}% ({np.mean(f3>0)*100:3.0f}% up) | 1y {np.median(f12)*100:+5.1f}% ({np.mean(f12>0)*100:3.0f}% up) | "
          f"further fall med {np.median(fall)*100:+5.1f}% worst {fall.min()*100:+4.0f}%")


o = osc.values; h = hlima.values
cross_up = lambda x, t: np.r_[False, (x[1:] > t) & (x[:-1] <= t)]
print('\n=== A. first trigger of each episode (>=63 trading days apart); forward = S&P price return ===')
print(f"{'':>40} {'n':>3} | medians; share up; further fall = worst close within 126d vs trigger close")
base = lambda hz: np.median([px[i + hz] / px[i] - 1 for i in range(n - hz)])
print(f"{'any day (baseline)':>40} {'':>3} | 1m {base(21)*100:+5.1f}% | 3m {base(63)*100:+5.1f}% | 1y {base(252)*100:+5.1f}%")
row('McClellan osc < -80 (script 1)', events(o < -80))
row('McClellan osc < -100', events(o < -100))
row('McClellan osc < 5th pct', events(o < osc.quantile(.05)))
row('osc crosses back above -80', events(cross_up(np.nan_to_num(o, nan=0), -80)))
row('HiLo 10d SMA < 5 (script 2)', events(h < 5))
row('HiLo 10d SMA < 10', events(h < 10))
row('HiLo 10d SMA crosses back above 5 (buy)', events(cross_up(np.nan_to_num(h, nan=50), 5)))
row('HiLo 10d SMA crosses back above 10', events(cross_up(np.nan_to_num(h, nan=50), 10)))
print('--- reference signals on the same dates ---')
row('VIX >= 30', events(v >= 30))
row('S&P -10% from high', events(dd <= -0.10))
row('S&P -20% from high', events(dd <= -0.20))
row('reclaim 200d avg while -10% down', events(np.r_[False, (dd[1:] <= -0.10) & (px[1:] > ma200[1:]) & (px[:-1] <= ma200[:-1])]))
row('osc<-80 AND -10% from high', events((o < -80) & (dd <= -0.10)))
row('osc<-80 AND VIX>=30', events((o < -80) & (v >= 30)))
row('HiLo<10 AND -10% from high', events((h < 10) & (dd <= -0.10)))

print('\n=== B. every trigger date, so you can judge them ===')
for name, ev in (('osc<-80', events(o < -80)), ('HiLo<5', events(h < 5)), ('HiLo crosses above 5', events(cross_up(np.nan_to_num(h, nan=50), 5)))):
    print(name + ':', ', '.join(f"{dates[i].date()} ({px[i+63]/px[i]*100-100:+.0f}% 3m)" if i + 63 < n else f'{dates[i].date()} (open)' for i in ev))

print('\n=== C. right now ===')
print(f'{dates[-1].date()}: osc {o[-1]:.0f} (days osc<-80 in last 20: {(o[-20:] < -80).sum()}), HiLo 10d SMA {h[-1]:.1f}, new highs/lows in panel: {int(hi.iloc[-1])}/{int(lo.iloc[-1])}, S&P drawdown {dd[-1]*100:.1f}%, VIX {v[-1]:.1f}')
