"""Calculate position size based on account, risk %, and stop distance."""

from src.config import RISK_PER_TRADE


def calculate_position_size(
    account_balance: float,
    entry_price: float,
    stop_loss: float,
    risk_pct: float = RISK_PER_TRADE,
    pip_value: float = 0.0001,
) -> dict:
    """Calculate position size in units.

    Args:
        account_balance: current account balance
        entry_price: planned entry price
        stop_loss: planned stop loss price
        risk_pct: fraction of account to risk (e.g. 0.01 = 1%)
        pip_value: value of one pip (0.0001 for most forex, 0.01 for JPY)

    Returns:
        dict with position_size (units), risk_amount, stop_pips
    """
    risk_amount = account_balance * risk_pct
    stop_distance = abs(entry_price - stop_loss)

    if stop_distance == 0:
        return {"position_size": 0, "risk_amount": risk_amount, "stop_pips": 0}

    # Defense-in-depth: reject sub-5-pip stops regardless of upstream checks
    min_stop_distance = pip_value * 5
    if stop_distance < min_stop_distance:
        return {"position_size": 0, "risk_amount": risk_amount, "stop_pips": round(stop_distance / pip_value, 1)}

    stop_pips = stop_distance / pip_value
    # Position size = risk_amount / (stop_pips * pip_value)
    # For standard forex: 1 unit = $0.0001 per pip
    position_size = risk_amount / stop_distance

    return {
        "position_size": round(position_size),
        "risk_amount": round(risk_amount, 2),
        "stop_pips": round(stop_pips, 1),
    }
