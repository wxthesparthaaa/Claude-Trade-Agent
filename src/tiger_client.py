"""
Loads Tiger Open API credentials from config/tiger_openapi_config.properties
and returns a ready-to-use client config.

Never hardcode tiger_id, account, or private_key here — they live only in
the git-ignored properties file (locally) or in Render environment
variables (when deployed).
"""
import os
from tigeropen.tiger_open_config import TigerOpenClientConfig

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")


def get_client_config(sandbox: bool = False) -> TigerOpenClientConfig:
    """
    sandbox=True uses Tiger's separate sandbox environment (different keys,
    dev-only). For normal paper trading, leave this False — paper trading
    uses the PROD environment with your paper account number, which is the
    recommended way to test per Tiger's own docs.
    """
    if not os.path.isdir(CONFIG_DIR):
        raise FileNotFoundError(
            f"Expected a config directory at {CONFIG_DIR}. "
            "Copy your Tiger properties file there as tiger_openapi_config.properties."
        )
    config = TigerOpenClientConfig(props_path=CONFIG_DIR, sandbox_debug=sandbox)
    return config
