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
) -> str:
    header = f"[{portfolio_label}]\n" if portfolio_label else ""
    text = (
        f"{header}Total Capital: ${capital:,.2f}\n"
        f"Gains for the day: ${gain_amount:,.2f} ({gain_pct:+.2%})"
    )
    if fomc_note:
        text += f"\n{fomc_note}"
    if news_summary_text:
        text += f"\n\n{news_summary_text}"
    return text


def format_shortlist_telegram(entries: List[Any], symbol_names: dict) -> str:
    """
    entries: shortlist.ShortlistEntry objects (or anything with .symbol/
    .confidence_pct), sorted by confidence descending -- as returned by
    shortlist.load_shortlist/update_shortlist. symbol_names: universe.
    SYMBOL_NAMES (or any {ticker: display name} dict) -- falls back to
    the bare ticker for anything not listed.

    This is deliberately a Telegram-only presentation -- the dashboard's
    own shortlist panel keeps its existing ticker/sleeve/delta format
    unchanged; this is a separate, simpler digest for the chat.
    """
    lines = ["Claude Stock Trading Shortlist:", ""]
    for e in entries:
        name = symbol_names.get(e.symbol, e.symbol)
        lines.append(f"{name} ({e.symbol}) - {e.confidence_pct:.0f}%")
    return "\n".join(lines)


def format_order_placed_update(
    placed_orders: List[Any],
    total_capital: float,
    total_invested_after: float,
) -> str:
    """
    placed_orders: duck-typed against execution.OrderInstruction -- objects
        with .symbol, .action ("BUY"|"SELL"), .quantity, .notional (the
        actual $ value of that order, reused rather than recomputed from a
        possibly-stale price).
    total_capital: the strategy's total tracked capital (e.g. $1,000), not
        Tiger's raw account balance.
    total_invested_after: total market value of all held positions AFTER
        this batch of orders, used to report overall margin utilization,
        not just this batch's own size.
    """
    lines = ["Orders placed:"]
    for o in placed_orders:
        pct_of_capital = o.notional / total_capital if total_capital > 0 else 0.0
        lines.append(
            f"  {o.action} {o.quantity} {o.symbol} = ${o.notional:,.2f} "
            f"({pct_of_capital:.1%} of ${total_capital:,.0f})"
        )

    utilization_pct = total_invested_after / total_capital if total_capital > 0 else 0.0
    cash_remaining = total_capital - total_invested_after
    lines.append("")
    lines.append(
        f"Total invested: ${total_invested_after:,.2f} of ${total_capital:,.2f} "
        f"({utilization_pct:.1%} margin used)"
    )
    lines.append(f"Cash remaining: ${cash_remaining:,.2f} ({1 - utilization_pct:.1%})")
    return "\n".join(lines)


def format_pending_approvals_alert(portfolio_label: str, items: List[dict]) -> str:
    """
    items: plain dicts as persisted by pending_approvals.write_pending_
    approvals/load_pending_approvals (symbol/action/quantity/
    position_type keys). Distinct from format_daily_update -- that one
    reports capital/gains once a day and never mentions pending
    approvals at all. This is sent specifically when the SG/HK-hours
    scan finds something worth reviewing while those markets are
    actually open (see app.py::scheduled_asia_hours_scan), so a real
    trade opportunity doesn't just sit unnoticed until the once-daily
    capital update.
    """
    header = f"[{portfolio_label}] " if portfolio_label else ""
    lines = [f"{header}SG/HK markets are open -- {len(items)} pending approval(s) ready to review:"]
    for item in items:
        position_type = item.get("position_type", "long")
        if position_type == "short":
            verb = "SHORT"
        elif position_type == "cover":
            verb = "COVER"
        else:
            verb = item["action"].upper()
        lines.append(f"  {verb} {item['quantity']} {item['symbol']}")
    return "\n".join(lines)


def format_weekly_update(
    capital: float,
    gain_amount: float,
    gain_pct: float,
    lessons: str,
    strategy_changes: List[str],
    portfolio_label: str = "",
) -> str:
    header = f"[{portfolio_label}]\n" if portfolio_label else ""
    changes_text = "\n".join(f"- {c}" for c in strategy_changes) if strategy_changes else "None"
    return (
        f"{header}Total Capital: ${capital:,.2f}\n"
        f"Gains for the week: ${gain_amount:,.2f} ({gain_pct:+.2%})\n"
        f"Lessons observed:\n{lessons}\n"
        f"Changes to strategy (if any):\n{changes_text}"
    )
