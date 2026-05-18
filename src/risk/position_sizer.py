"""Position sizing.

Sizes a position so a stop-out costs `risk_pct × account_balance` in the
account currency. Handles three pair classes:

- Quote currency = account currency (e.g. EUR_USD with USD account):
  PnL per unit per pip = 1 quote = 1 account → conversion rate = 1.0.
- Base currency = account currency (e.g. USD_JPY with USD account):
  PnL per unit per pip is in JPY → rate = 1 / entry_price (JPY/USD inverse).
- Neither base nor quote = account (cross pair, e.g. EUR_JPY):
  Caller must supply quote_to_account_rate via the parameter.

The bug this fixes: previously `position_size = risk_amount / stop_distance`
was used for every pair. Correct only for case 1. For USD_JPY this under-
sized positions by a factor of ~entry_price (~150-160×); for USD_CAD by
~1.37×; for crosses by similar amounts.
"""

from src.config import RISK_PER_TRADE


def quote_to_account_rate(
    pair: str,
    entry_price: float,
    account_currency: str = "USD",
) -> float | None:
    """Rate to convert one unit of QUOTE currency to one unit of account currency.

    Returns None for cross pairs (neither base nor quote is the account
    currency) — caller must supply an externally-fetched rate.

    Examples (account=USD):
        EUR_USD → 1.0     (quote is USD already)
        GBP_USD → 1.0
        USD_JPY → 1/price (JPY/USD inverse, ~0.0063 at price=159)
        USD_CAD → 1/price (~0.73 at price=1.37)
        EUR_JPY → None    (need USD_JPY or JPY_USD external)
        EUR_GBP → None    (need USD_GBP or GBP_USD external)
    """
    base, _, quote = pair.partition("_")
    if not quote:
        raise ValueError(f"unrecognized pair format: {pair!r}")
    if quote == account_currency:
        return 1.0
    if base == account_currency:
        if entry_price <= 0:
            raise ValueError(f"entry_price must be positive, got {entry_price}")
        return 1.0 / entry_price
    return None


def calculate_position_size(
    account_balance: float,
    entry_price: float,
    stop_loss: float,
    risk_pct: float = RISK_PER_TRADE,
    pip_value: float = 0.0001,
    quote_to_account_rate: float = 1.0,
) -> dict:
    """Calculate position size in units.

    Args:
        account_balance: current account balance in account currency
        entry_price: planned entry price (in QUOTE per BASE)
        stop_loss: planned stop loss price
        risk_pct: fraction of account to risk (e.g. 0.02 = 2%)
        pip_value: value of one pip (0.0001 for most forex, 0.01 for JPY)
        quote_to_account_rate: how many account-currency units one quote-currency
            unit is worth. 1.0 for USD-quoted pairs (EUR_USD etc.), 1/entry_price
            for USD-base pairs (USD_JPY etc.), externally-supplied for crosses.
            See quote_to_account_rate() helper.

    Returns:
        dict with position_size (units), risk_amount, stop_pips
    """
    risk_amount = account_balance * risk_pct
    stop_distance = abs(entry_price - stop_loss)

    if stop_distance == 0:
        return {"position_size": 0, "risk_amount": risk_amount, "stop_pips": 0}

    if quote_to_account_rate <= 0:
        return {"position_size": 0, "risk_amount": risk_amount, "stop_pips": 0}

    # Defense-in-depth: reject sub-5-pip stops regardless of upstream checks
    min_stop_distance = pip_value * 5
    if stop_distance < min_stop_distance:
        return {"position_size": 0, "risk_amount": risk_amount, "stop_pips": round(stop_distance / pip_value, 1)}

    stop_pips = stop_distance / pip_value
    # Per-unit loss in account currency at the stop:
    #   stop_distance (in QUOTE per BASE) × quote_to_account_rate (account per QUOTE)
    # Position size to make total loss = risk_amount:
    #   units = risk_amount / (stop_distance × quote_to_account_rate)
    per_unit_loss = stop_distance * quote_to_account_rate
    position_size = risk_amount / per_unit_loss

    return {
        "position_size": round(position_size),
        "risk_amount": round(risk_amount, 2),
        "stop_pips": round(stop_pips, 1),
    }
