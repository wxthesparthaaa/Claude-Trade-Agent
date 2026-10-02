import sys, time; sys.path.insert(0, 'research')
from harness import *
t=time.time()
for un in ('static','full'):
    U=universe(un)
    print('==', un)
    for name,p in [('OLD (band0, stop15)',Params(band=0.0,stop=0.15)),('LIVE (band20, stop20)',Params()),
                   ('LIVE no-halt',Params(dd_halt=None))]:
        r=simulate(U,p,'2020-03-01','2026-10-03'); print(f'{name:24s}', fmt(r))
print(time.time()-t)
