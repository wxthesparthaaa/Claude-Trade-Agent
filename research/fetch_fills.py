"""Fetch real filled orders from Tiger for a date window -> research/data/fills_<start>_<end>.json"""
import json, sys, os
from datetime import datetime, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from tiger_client import get_client_config
from tigeropen.trade.trade_client import TradeClient

start, end = sys.argv[1], sys.argv[2]
ms = lambda s: int(datetime.strptime(s, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp() * 1000)
tc = TradeClient(get_client_config())
orders = tc.get_filled_orders(start_time=ms(start), end_time=ms(end))
out = []
for o in orders or []:
    out.append(dict(symbol=o.contract.symbol, action=o.action, qty=o.filled, price=o.avg_fill_price,
                    commission=o.commission, time=datetime.fromtimestamp((o.trade_time or o.order_time) / 1000, tz=timezone.utc).isoformat(),
                    realized_pnl=getattr(o, 'realized_pnl', None), id=o.id))
out.sort(key=lambda r: r['time'])
path = os.path.join(os.path.dirname(__file__), 'data', f'fills_{start}_{end}.json')
json.dump(out, open(path, 'w'), indent=1)
print(len(out), 'fills ->', path)
for r in out: print(r)
