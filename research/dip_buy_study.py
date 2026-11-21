"""Does "buy big when the S&P is down 20% from its high" work -- and is there a better signal?  (2026-11-21)

Data: S&P 500 price index 1930-2026 and VIX 1990-2026 (research/data/index, Yahoo chart API; price only, no dividends,
so every strategy below is compared on the same footing).
A  event study: first crossing of -10/-15/-20/-25/-30% from the all-time high, per drawdown episode (1950+)
B  reserve deployment: monthly savings, DCA vs "hoard cash, deploy at the signal" vs a ladder
C  other signals: VIX spikes, 200-day-average reclaim, -20% + VIX
D  where the market is right now
Usage: python research/dip_buy_study.py
"""
import os
import numpy as np, pandas as pd

D = os.path.join(os.path.dirname(__file__), 'data', 'index')
# Start at 1950 and take the running high from there: the index was still below its 1929 high until 1954, which would
# otherwise register as a bogus "-20%" trigger on day one.
sp = pd.read_csv(os.path.join(D, 'GSPC.csv'), parse_dates=['date']).set_index('date')['close'].loc['1950-01-01':]
vix = pd.read_csv(os.path.join(D, 'VIX.csv'), parse_dates=['date']).set_index('date')['close']
px = sp.values; dates = sp.index; n = len(px)
ath = np.maximum.accumulate(px)
dd = px / ath - 1
H = {'1m': 21, '3m': 63, '6m': 126, '1y': 252, '2y': 504}

# episode id: a new episode starts each time the index makes a new all-time high
epi = np.cumsum(np.r_[True, px[1:] >= ath[:-1]])
start1950 = int(np.searchsorted(dates.values, np.datetime64('1950-01-01')))


def first_crossings(th, begin=start1950):
    out = []
    for e in np.unique(epi[begin:]):
        idx = np.where((epi == e) & (dd <= -th))[0]
        idx = idx[idx >= begin]
        if len(idx):
            out.append(int(idx[0]))
    return out


def further(i):
    """worst close from the trigger until the index regains its prior all-time high, vs the trigger close."""
    j = i
    while j + 1 < n and epi[j + 1] == epi[i]:
        j += 1
    return px[i:j + 1].min() / px[i] - 1, (j - i) if j + 1 < n else None


print('=== A. what happened after the S&P first fell X% from its high (episodes since 1950; price return) ===')
base = {k: np.nanmean([px[i + h] / px[i] - 1 for i in range(start1950, n - h)]) for k, h in H.items()}
print(f"unconditional average forward return, any day: " + ', '.join(f'{k} {v*100:+.1f}%' for k, v in base.items()))
print(f"{'trigger':>8} {'n':>3} | {'median 3m':>9} {'median 1y':>9} {'mean 1y':>8} {'1y>0':>5} {'1y<-10%':>8} | {'median further fall':>19} {'worst':>7} {'fell >=10% more':>15}")
for th in (0.10, 0.15, 0.20, 0.25, 0.30):
    ev = first_crossings(th)
    f3 = [px[i + 63] / px[i] - 1 for i in ev if i + 63 < n]
    f1 = np.array([px[i + 252] / px[i] - 1 for i in ev if i + 252 < n])
    fr = np.array([further(i)[0] for i in ev])
    print(f"{-th:>8.0%} {len(ev):>3} | {np.median(f3)*100:+8.1f}% {np.median(f1)*100:+8.1f}% {f1.mean()*100:+7.1f}% {np.mean(f1 > 0)*100:4.0f}% {np.mean(f1 < -0.10)*100:7.0f}% | {np.median(fr)*100:+18.1f}% {fr.min()*100:+6.0f}% {np.mean(fr <= -0.10)*100:14.0f}%")
print('-20% triggers:')
for i in first_crossings(0.20):
    fr, days = further(i)
    f1 = px[i + 252] / px[i] - 1 if i + 252 < n else float('nan')
    print(f"  {dates[i].date()}  S&P {px[i]:7.0f}  1y later {f1*100:+6.1f}%   further fall {fr*100:+5.0f}%   days to regain old high: {days}")

print('\n=== B. $1/month of savings, 1950-2026: DCA vs hoarding cash for a signal (terminal wealth in index units, price return) ===')


def run(rule, cash_rate=0.0):
    units = cash = 0.0
    deployed_eps, hoard_days, max_cash = set(), 0, 0.0
    last_m = None
    for i in range(start1950, n):
        m = (dates[i].year, dates[i].month)
        if cash and cash_rate:
            cash *= 1 + cash_rate / 252
        if m != last_m:
            last_m = m
            cash += 1.0
        frac = rule(i, deployed_eps)
        if frac > 0 and cash > 0:
            amt = cash * frac
            units += amt / px[i]; cash -= amt
        hoard_days += cash > 0
        max_cash = max(max_cash, cash)
    return units * px[-1] + cash, cash, max_cash


def dca(i, seen):
    return 1.0


def make_wait(th):
    def f(i, seen):                      # deploy everything the moment the drawdown reaches th, and keep investing until a new high
        return 1.0 if dd[i] <= -th else 0.0
    return f


def make_ladder(ths):
    def f(i, seen):
        for k, th in enumerate(ths):
            if dd[i] <= -th and (epi[i], k) not in seen:
                seen.add((epi[i], k))
                return 1.0 / (len(ths) - k)   # 1/3, then 1/2 of what is left, then all
        return 1.0 if dd[i] <= -ths[0] else 0.0
    return f


total = sum(1 for i in range(start1950, n) if i == start1950 or (dates[i].year, dates[i].month) != (dates[i - 1].year, dates[i - 1].month))
print(f'contributions: {total} months')
for cr in (0.0, 0.03):
    w0, _, _ = run(dca)
    print(f'cash earns {cr:.0%}/yr:')
    for label, rule in (('DCA (invest at once)', dca), ('wait for -10%, then buy', make_wait(0.10)), ('wait for -20%, then buy', make_wait(0.20)),
                        ('wait for -30%, then buy', make_wait(0.30)), ('ladder -10/-20/-30', make_ladder((0.10, 0.20, 0.30)))):
        w, c, mc = run(rule, cr)
        print(f'  {label:26s} final wealth {w:8.1f} = {w/w0*100:5.1f}% of DCA | cash left at end {c:6.1f} | peak idle cash {mc:6.1f} months of savings')

print('\n=== C. other signals (1990+, VIX data): forward returns from the FIRST trigger of each episode ===')
v = vix.reindex(dates).ffill()
ma200 = pd.Series(px, index=dates).rolling(200).mean().values
begin = int(np.searchsorted(dates.values, np.datetime64('1990-01-01')))


def triggers(cond, quiet=63):
    out, last = [], -10 ** 9
    for i in range(begin, n):
        if cond(i) and i - last > quiet:
            out.append(i)
        if cond(i):
            last = i
    return out


sigs = {
    'S&P -20% from high': lambda i: dd[i] <= -0.20,
    'S&P -10% from high': lambda i: dd[i] <= -0.10,
    'VIX >= 30': lambda i: v.values[i] >= 30,
    'VIX >= 40': lambda i: v.values[i] >= 40,
    '-20% AND VIX >= 30': lambda i: dd[i] <= -0.20 and v.values[i] >= 30,
    'reclaim 200d avg while -10% down': lambda i: i > 0 and dd[i] <= -0.10 and px[i] > ma200[i] and px[i - 1] <= ma200[i - 1],
}
print(f"{'signal':>34} {'n':>3} | {'median 1y':>9} {'1y>0':>5} | {'median 3m':>9} | {'median further fall':>19} {'worst':>7}")
for name, cond in sigs.items():
    ev = triggers(cond)
    f1 = np.array([px[i + 252] / px[i] - 1 for i in ev if i + 252 < n]); f3 = np.array([px[i + 63] / px[i] - 1 for i in ev if i + 63 < n])
    fall = np.array([px[i:min(i + 126, n)].min() / px[i] - 1 for i in ev])
    print(f"{name:>34} {len(ev):>3} | {np.median(f1)*100:+8.1f}% {np.mean(f1 > 0)*100:4.0f}% | {np.median(f3)*100:+8.1f}% | {np.median(fall)*100:+18.1f}% {fall.min()*100:+6.0f}%")

print('\n=== D. right now ===')
i = n - 1
print(f"{dates[i].date()}: S&P {px[i]:.0f}, all-time high {ath[i]:.0f} ({dates[int(np.argmax(px))].date()}), drawdown {dd[i]*100:.1f}%, VIX {v.values[i]:.1f}, "
      f"vs 200-day avg {(px[i]/ma200[i]-1)*100:+.1f}%")
print('worst close-to-close drawdown in the last 60 sessions:', f"{(px[-60:]/np.maximum.accumulate(px[-60:])-1).min()*100:.1f}%")
