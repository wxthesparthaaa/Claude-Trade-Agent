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
from typing import List

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")
CONFIG_PATH = os.path.join(CONFIG_DIR, "telegram_config.properties")


@dataclass
class TelegramConfig:
    bot_token: str
    chat_id: str


def get_telegram_config() -> TelegramConfig:
    if not os.path.isfile(CONFIG_PATH):
        raise FileNotFoundError(
            f"Expected {CONFIG_PATH}. Create a bot via @BotFather on Telegram, "
            "get your chat ID (e.g. via @userinfobot), and write a file there "
            "with bot_token=... and chat_id=... on separate lines."
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


def format_daily_update(capital: float, gain_amount: float, gain_pct: float) -> str:
    return (
        f"Total Capital: ${capital:,.2f}\n"
        f"Gains for the day: ${gain_amount:,.2f} ({gain_pct:+.2%})"
    )


def format_weekly_update(
    capital: float,
    gain_amount: float,
    gain_pct: float,
    lessons: str,
    strategy_changes: List[str],
) -> str:
    changes_text = "\n".join(f"- {c}" for c in strategy_changes) if strategy_changes else "None"
    return (
        f"Total Capital: ${capital:,.2f}\n"
        f"Gains for the week: ${gain_amount:,.2f} ({gain_pct:+.2%})\n"
        f"Lessons observed:\n{lessons}\n"
        f"Changes to strategy (if any):\n{changes_text}"
    )
