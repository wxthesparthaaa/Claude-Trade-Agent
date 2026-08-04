"""
Loads Tiger Open API credentials from config/tiger_openapi_config.properties
and returns a ready-to-use client config.

Never hardcode tiger_id, account, or private_key here — they live only in
the git-ignored properties file (locally) or in Render environment
variables (when deployed).
"""
import os
from tigeropen.tiger_open_config import TigerOpenClientConfig

from state_paths import STATE_DIR

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")

_ENV_TO_PROPERTY = {
    "TIGER_PRIVATE_KEY_PK1": "private_key_pk1",
    "TIGER_PRIVATE_KEY_PK8": "private_key_pk8",
    "TIGER_ID": "tiger_id",
    "TIGER_ACCOUNT": "account",
    "TIGER_LICENSE": "license",
    "TIGER_ENV": "env",
}


def _synthesize_properties_dir() -> str:
    """
    Writes a tiger_openapi_config.properties file into STATE_DIR from
    TIGER_* env vars, in the same format config/README.md documents, and
    returns the directory containing it -- reuses the exact same tested
    TigerOpenClientConfig(props_path=...) code path rather than
    reconstructing the SDK's config object from individual fields.
    """
    os.makedirs(STATE_DIR, exist_ok=True)
    lines = [
        f"{prop}={os.environ[env_var]}"
        for env_var, prop in _ENV_TO_PROPERTY.items()
        if env_var in os.environ
    ]
    with open(os.path.join(STATE_DIR, "tiger_openapi_config.properties"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return STATE_DIR


def get_client_config(sandbox: bool = False) -> TigerOpenClientConfig:
    """
    sandbox=True uses Tiger's separate sandbox environment (different keys,
    dev-only). For normal paper trading, leave this False — paper trading
    uses the PROD environment with your paper account number, which is the
    recommended way to test per Tiger's own docs.

    Prefers the local config/tiger_openapi_config.properties file
    (unchanged local-dev behavior); if that's absent but TIGER_ID is set
    as an env var (a cloud deployment), synthesizes the same properties
    format from TIGER_* env vars instead.
    """
    local_file = os.path.join(CONFIG_DIR, "tiger_openapi_config.properties")
    if os.path.isfile(local_file):
        props_dir = CONFIG_DIR
    elif "TIGER_ID" in os.environ:
        props_dir = _synthesize_properties_dir()
    else:
        raise FileNotFoundError(
            f"Expected a properties file at {local_file}, or TIGER_ID (and the other TIGER_* "
            "env vars) to be set for a cloud deployment. Copy your Tiger properties file to "
            "config/tiger_openapi_config.properties, or set the TIGER_* environment variables."
        )
    return TigerOpenClientConfig(props_path=props_dir, sandbox_debug=sandbox)
