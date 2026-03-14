"""Base signal class for all signal types."""

from dataclasses import dataclass, field
from enum import Enum
import pandas as pd


class SignalDirection(Enum):
    BUY = "buy"
    SELL = "sell"


class SignalType(Enum):
    REVERSAL = "reversal"
    BUILDUP = "buildup"
    PULLBACK = "pullback"
    BOS = "bos"


@dataclass
class Signal:
    signal_type: SignalType
    direction: SignalDirection
    pair: str
    timeframe: str
    timestamp: pd.Timestamp
    entry_price: float
    stop_loss: float
    take_profit: float
    quality_score: float        # 0-100
    confluence_level: int       # number of confluent factors
    confidence: float           # 0-100 overall confidence
    reasons: list[str] = field(default_factory=list)

    @property
    def risk_reward_ratio(self) -> float:
        """Calculate the R:R ratio."""
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.take_profit - self.entry_price)
        return reward / risk if risk > 0 else 0

    @property
    def risk_pips(self) -> float:
        """Distance from entry to stop in pips (assumes forex 4/5 digit)."""
        return abs(self.entry_price - self.stop_loss) * 10000

    def to_dict(self) -> dict:
        return {
            "signal_type": self.signal_type.value,
            "direction": self.direction.value,
            "pair": self.pair,
            "timeframe": self.timeframe,
            "timestamp": str(self.timestamp),
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "quality_score": self.quality_score,
            "confluence_level": self.confluence_level,
            "confidence": self.confidence,
            "risk_reward": self.risk_reward_ratio,
            "reasons": self.reasons,
        }
