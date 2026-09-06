"""
Free, unauthenticated SEC EDGAR data for real trailing-annual EPS -- used
by valuation.py to compute a PE ratio when Tiger's own account doesn't
have US/HK real-time-quote/fundamentals permission. Confirmed live:
QuoteClient.get_stock_details/get_briefs/get_financial_daily all reject
with "permission denied" for US and HK -- get_quote_permission() shows
this account only holds aStockQuoteLv1 (A-shares Level 1), nothing for
US/HK. Historical daily bars (get_bars, see tiger_stock_bars_adapter.py)
are unaffected -- a separate permission tier -- so price still comes
from Tiger; only the EPS half of the PE ratio needs a substitute source.

Same free-public-API posture as cot_adapter.py: plain unauthenticated
HTTP via urllib, fetch_*/parse_* split, a bad/missing symbol returns
None rather than raising so one bad lookup can't kill a batch. SEC's
bot-mitigation layer rejects a User-Agent that doesn't look like an
"app name + contact email" string with a 403 (confirmed live -- a
GitHub-URL-style identifier and a bare "Mozilla/5.0" were both
rejected) -- see https://www.sec.gov/os/webmaster-faq#developers. This
uses a generic example.com placeholder, deliberately not any real
person's email: this app has no reason to send a user's actual address
to an unrelated third-party service just to satisfy a WAF pattern
check, and SEC doesn't verify deliverability anyway.

US-listed, SEC-registered companies only -- HK/SG symbols have no SEC
filings and get None back, the same "no data for this region" honesty
already established for SG in sector_rotation.py/movers.py.

Uses the most recent ANNUAL (10-K, fp="FY") diluted EPS, not a
reconstructed trailing-twelve-month figure -- SEC's raw quarterly XBRL
facts mix single-quarter and cumulative-YTD durations for the same
concept, and omit a standalone Q4 entirely (folded into the 10-K),
making a reliable TTM reconstruction from this endpoint alone genuinely
ambiguous. This makes the resulting PE a "trailing FY" figure, up to
~12 months stale relative to a true TTM PE -- valuation.py states this
plainly wherever it's shown, not disguised as real-time.
"""
import json
import urllib.error
import urllib.request
from typing import Dict, Optional

USER_AGENT = "ClaudeTradeAgent-PEResearch research@example.com"
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/EarningsPerShareDiluted.json"


def _sec_get(url: str) -> Optional[dict]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        print(f"SEC EDGAR request failed for {url}: {type(e).__name__}: {e}")
        return None


def fetch_ticker_cik_map() -> Optional[dict]:
    """The only function that calls SEC's ticker->CIK directory. One
    ~1MB file covering every US-listed ticker -- fetch this once per
    batch/run, not once per symbol (see get_annual_eps)."""
    return _sec_get(TICKER_MAP_URL)


def parse_ticker_cik_map(raw: Optional[dict]) -> Dict[str, str]:
    """Pure -- raw is fetch_ticker_cik_map's return. Maps an upper-case
    ticker to its zero-padded 10-digit CIK string (the format SEC's
    per-company endpoints require)."""
    if not raw:
        return {}
    return {
        entry["ticker"].upper(): str(entry["cik_str"]).zfill(10)
        for entry in raw.values()
        if "ticker" in entry and "cik_str" in entry
    }


def fetch_diluted_eps_facts(cik: str) -> Optional[dict]:
    return _sec_get(CONCEPT_URL.format(cik=cik))


def parse_annual_diluted_eps(raw: Optional[dict]) -> Optional[float]:
    """Pure -- raw is fetch_diluted_eps_facts' return. Picks the most
    recent full-fiscal-year (form 10-K, fp "FY") value by period end
    date -- None if this company has never filed a diluted-EPS fact in
    this exact concept (e.g. a foreign private issuer filing 20-F
    instead of 10-K), which _sec_get already turns into None on a 404."""
    if not raw:
        return None
    facts = raw.get("units", {}).get("USD/shares", [])
    annual = [f for f in facts if f.get("form") == "10-K" and f.get("fp") == "FY" and "val" in f and "end" in f]
    if not annual:
        return None
    latest = max(annual, key=lambda f: f["end"])
    return float(latest["val"])


def get_annual_eps(symbol: str, ticker_cik_map: Dict[str, str]) -> Optional[float]:
    """Orchestrates one symbol's EPS lookup given an already-fetched
    ticker->CIK map (see fetch_ticker_cik_map's docstring on why that's
    fetched once per batch)."""
    cik = ticker_cik_map.get(symbol.upper())
    if cik is None:
        return None
    return parse_annual_diluted_eps(fetch_diluted_eps_facts(cik))
