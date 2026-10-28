"""
Sends Telegram notifications via plain HTTPS calls to Telegram's Bot API --
no SDK dependency needed. Credentials load the same way Tiger's do
(tiger_client.get_client_config): from a gitignored properties file, never
hardcoded.

Left unconfigured until the user creates a bot via @BotFather and provides
a token + chat ID -- get_telegram_config() raises clearly if the file isn't
there yet rather than silently no-op-ing.
"""
import os
import urllib.request
import urllib.parse
from dataclasses import dataclass
from typing import Any, List

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")
CONFIG_PATH = os.path.join(CONFIG_DIR, "telegram_config.properties")


@dataclass
class TelegramConfig:
    bot_token: str
    chat_id: str


def get_telegram_config() -> TelegramConfig:
    """
    Prefers TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID env vars (a cloud
    deployment); falls back to the local properties file unchanged
    otherwise.
    """
    env_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    env_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if env_token and env_chat_id:
        return TelegramConfig(bot_token=env_token, chat_id=env_chat_id)

    if not os.path.isfile(CONFIG_PATH):
        raise FileNotFoundError(
            f"Expected {CONFIG_PATH}, or TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID env vars. "
            "Create a bot via @BotFather on Telegram, get your chat ID (e.g. via "
            "@userinfobot), and either write a file there with bot_token=... and "
            "chat_id=... on separate lines, or set the env vars."
        )
    values = {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return TelegramConfig(bot_token=values["bot_token"], chat_id=values["chat_id"])


def send_message(text: str, bot_token: str, chat_id: str, timeout: float = 10.0) -> None:
    """Plain HTTPS POST to Telegram's sendMessage endpoint. Raises on any non-2xx response."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"Telegram API returned status {response.status}")


def format_daily_update(
    capital: float, gain_amount: float, gain_pct: float,
    fomc_note: str = "", portfolio_label: str = "", news_summary_text: str = "",
    holdings_text: str = "", trades_text: str = "",
) -> str:
    """The 18:00 SGT daily message. Kept to what's actionable/relevant:
    capital and how it moved, what's held vs the strategy's targets
    (holdings_text), what traded since the last update (trades_text), and
    only if present, an FOMC flag and notable per-symbol news. The macro
    regime paragraph (futures positioning / breadth / short-selling gate)
    that used to be here was removed -- it read as jargon and never
    changed what the user needed to know or do; it's still on the
    dashboard."""
    header = f"[{portfolio_label}] " if portfolio_label else ""
    sign = "+" if gain_amount >= 0 else "-"
    lines = [
        f"{header}Daily summary",
        f"Total Capital: ${capital:,.2f}",
        f"Change since the last update: {sign}${abs(gain_amount):,.2f} ({gain_pct:+.2%})",
    ]
    if holdings_text:
        lines.append(holdings_text)
    if trades_text:
        lines.append(trades_text)
    if fomc_note:
        lines.append(fomc_note)
    if news_summary_text:
        lines.append("")
        lines.append(news_summary_text)
    return "\n".join(lines)


def format_holdings_line(
    positions: List[dict], total_capital: float, sleeve_targets: dict = None,
) -> str:
    """One compact line: how much is invested vs cash, and for a two-sleeve
    portfolio, where each sleeve sits against the strategy's target.
    positions: snapshot-style dicts with "sleeve" and "market_value".
    sleeve_targets: {"core": 0.40, "satellite": 0.60} -- pass None/{} for
    a single-sleeve portfolio (dividend), which then just reports
    invested vs cash."""
    if total_capital <= 0:
        return ""
    invested = sum(p.get("market_value", 0.0) for p in positions)
    invested_pct = invested / total_capital
    text = (
        f"Holdings: {len(positions)} position{'s' if len(positions) != 1 else ''}, "
        f"{invested_pct:.0%} invested / {max(0.0, 1 - invested_pct):.0%} cash"
    )
    if sleeve_targets:
        parts = []
        for sleeve, target in sleeve_targets.items():
            if target <= 0:
                continue
            actual = sum(p.get("market_value", 0.0) for p in positions if p.get("sleeve") == sleeve) / total_capital
            parts.append(f"{sleeve.capitalize()} {actual:.0%} (target {target:.0%})")
        if parts:
            text += ". " + ", ".join(parts)
    return text


def format_trades_since(fills: List[dict]) -> str:
    """fills: dicts with action ("BUY"/"SELL"), symbol, quantity,
    commission -- real Tiger fills since the previous update. Groups
    buys and sells onto one line each so a busy rebalance day stays
    readable."""
    if not fills:
        return "Trades since the last update: none"
    commission = sum(f.get("commission") or 0.0 for f in fills)
    n = len(fills)
    lines = [f"Trades since the last update: {n} order{'s' if n != 1 else ''}, ${commission:,.2f} in commissions"]
    for action in ("BUY", "SELL"):
        items = [f"{f['symbol']} {f['quantity']:g}" for f in fills if f["action"] == action]
        if items:
            lines.append(f"  {action}: {', '.join(items)}")
    return "\n".join(lines)


def explain_order_reason(reason: str) -> str:
    """Plain-English version of an execution.OrderInstruction.reason (or an
    exit rule's reason) -- so an order alert says WHY, in terms of the
    strategy, instead of just what."""
    import re
    r = (reason or "").strip()
    target = re.search(r"target (\d+)% of capital", r)
    target_text = f" ({target.group(1)}% of capital)" if target else ""
    if r.startswith("stop_loss_short"):
        m = re.search(r"up (-?[\d.]+)%", r)
        return f"stop-loss hit on the short (price up {m.group(1)}%)" if m else "stop-loss hit on the short"
    if r.startswith("stop_loss"):
        m = re.search(r"down (-?[\d.]+)%", r)
        return f"stop-loss hit ({m.group(1)}% from entry)" if m else "stop-loss hit"
    if r.startswith("momentum_reversal"):
        return "trend turned negative -- exiting"
    if "no longer a target position -- full exit" in r:
        return "no longer one of the top picks -- selling out"
    if "no longer a target position -- full cover" in r:
        return "no longer a target -- covering the short"
    if r.startswith("increase toward target"):
        return f"buying up to its target size{target_text}"
    if r.startswith("reduce toward target"):
        return f"trimming back to its target size{target_text}"
    return r


def format_order_placed_update(
    placed_orders: List[Any],
    total_capital: float,
    total_invested_after: float,
    portfolio_label: str = "",
) -> str:
    """
    placed_orders: duck-typed against execution.OrderInstruction -- objects
        with .symbol, .action ("BUY"|"SELL"), .quantity, .notional (the
        actual $ value of that order, reused rather than recomputed from a
        possibly-stale price), and optionally .reason (explained in plain
        English by explain_order_reason).
    total_capital: the strategy's total tracked capital (e.g. $1,000), not
        Tiger's raw account balance.
    total_invested_after: total market value of all held positions AFTER
        this batch of orders, used to report overall utilization, not just
        this batch's own size.
    portfolio_label: "Growth Portfolio" / "Dividend Portfolio" -- both
        portfolios share one Tiger account and one Telegram chat, so
        without it two identical-looking alerts can't be told apart.
    """
    header = f"[{portfolio_label}] " if portfolio_label else ""
    lines = [f"{header}Orders placed:"]
    for o in placed_orders:
        pct_of_capital = o.notional / total_capital if total_capital > 0 else 0.0
        line = f"  {o.action} {o.quantity} {o.symbol} = ${o.notional:,.2f} ({pct_of_capital:.1%} of capital)"
        why = explain_order_reason(getattr(o, "reason", ""))
        if why:
            line += f" -- {why}"
        lines.append(line)

    utilization_pct = total_invested_after / total_capital if total_capital > 0 else 0.0
    cash_remaining = total_capital - total_invested_after
    lines.append("")
    lines.append(
        f"Invested: ${total_invested_after:,.2f} of ${total_capital:,.2f} ({utilization_pct:.1%}) | "
        f"cash: ${cash_remaining:,.2f} ({1 - utilization_pct:.1%})"
    )
    return "\n".join(lines)


def _signed_usd(amount: float) -> str:
    return f"{'+' if amount >= 0 else '-'}${abs(amount):,.2f}"


def format_weekly_summary(
    capital: float,
    gain_amount: float,
    gain_pct: float,
    realized_by_symbol: dict,
    portfolio_label: str = "",
    pause_changes: List[str] = None,
) -> str:
    """Saturday digest. gain_amount is the ledger's net P&L for the week
    (after commissions, includes unrealized); realized_by_symbol is the
    realized P&L of each trade CLOSED this week, straight from the trade
    journal. No lessons/strategy-change commentary -- that review was
    removed."""
    header = f"[{portfolio_label}]\n" if portfolio_label else ""
    lines = [
        f"{header}Weekly summary",
        f"P&L for the week: {_signed_usd(gain_amount)} ({gain_pct:+.2%}), net of commissions",
        f"Total Capital: ${capital:,.2f}",
    ]
    if realized_by_symbol:
        realized_total = sum(realized_by_symbol.values())
        lines.append(f"Realized on trades closed this week: {_signed_usd(realized_total)}")
        for symbol, pnl in sorted(realized_by_symbol.items(), key=lambda kv: kv[1], reverse=True):
            lines.append(f"  {symbol}: {_signed_usd(pnl)}")
    else:
        lines.append("No trades closed this week.")
    if pause_changes:
        lines.append("Auto-pause changes:")
        lines.extend(f"- {c}" for c in pause_changes)
    return "\n".join(lines)
