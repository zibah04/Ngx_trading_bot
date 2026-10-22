"""
NGX Algorithmic Trading Bot - Strategy & Broker Configuration
"""

from dataclasses import dataclass, field
import math
from typing import Dict, Optional


@dataclass
class TickerStrategyConfig:
    symbol: str
    x_buy_discount_pct: float = 5.0       # X: Buy discount %
    y_profit_target_pct: float = 10.0     # Y: Net profit target %
    z_capital_budget_naira: float = 100_000.0  # Z: Maximum Naira budget per order
    n_cycle_count: int = 3                # N: Target cycles to execute
    entry_fee_pct: float = 1.5            # 1.5% entry fee (SEC, NGX, CSCS, broker)
    exit_fee_pct: float = 1.5             # 1.5% exit fee
    min_order_interval_seconds: float = 2.0
    fill_polling_interval_seconds: float = 1.5
    order_timeout_seconds: float = 600.0

    def __post_init__(self) -> None:
        numeric = (self.x_buy_discount_pct, self.y_profit_target_pct,
                   self.z_capital_budget_naira, self.entry_fee_pct, self.exit_fee_pct,
                   self.min_order_interval_seconds, self.fill_polling_interval_seconds,
                   self.order_timeout_seconds)
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError("Strategy values must be finite.")
        if not self.symbol or self.symbol != self.symbol.strip().upper():
            raise ValueError("Symbol must be non-empty uppercase text without surrounding whitespace.")
        if not 0 <= self.x_buy_discount_pct < 100:
            raise ValueError("Buy discount must be between 0 and 100 percent.")
        if self.y_profit_target_pct < 0 or self.z_capital_budget_naira <= 0:
            raise ValueError("Profit target must be non-negative and budget must be positive.")
        if type(self.n_cycle_count) is not int or self.n_cycle_count < 1:
            raise ValueError("Cycle count must be at least 1.")
        if not 0 <= self.entry_fee_pct < 100 or not 0 <= self.exit_fee_pct < 100:
            raise ValueError("Fee percentages must be between 0 and 100.")
        if min(
            self.min_order_interval_seconds,
            self.fill_polling_interval_seconds,
            self.order_timeout_seconds,
        ) <= 0:
            raise ValueError("Order intervals and timeout must be positive.")


@dataclass
class BotSafetyConfig:
    enable_kill_switch: bool = False
    daily_price_limit_pct: float = 10.0   # Requires a broker-supplied previous close
    network_retry_max_attempts: int = 5
    network_retry_backoff_factor: float = 1.5
    database_path: str = "ngx_trading_bot.db"
    max_quote_age_seconds: float = 10.0
    max_spread_pct: float = 5.0
    max_total_budget_naira: float = 1_000_000.0
    cancellation_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        limits = (self.daily_price_limit_pct, self.max_quote_age_seconds,
                  self.max_spread_pct, self.max_total_budget_naira,
                  self.cancellation_timeout_seconds, self.network_retry_backoff_factor)
        if not all(math.isfinite(value) and value > 0 for value in limits):
            raise ValueError("Safety limits must be finite and positive.")
        if not 0 < self.daily_price_limit_pct < 100:
            raise ValueError("Daily price limit must be below 100 percent.")
        if type(self.network_retry_max_attempts) is not int or self.network_retry_max_attempts < 1:
            raise ValueError("Network retry attempts must be at least 1.")
        if self.network_retry_backoff_factor < 1:
            raise ValueError("Network retry backoff factor must be at least 1.")
        if not self.database_path:
            raise ValueError("Database path must not be empty.")


@dataclass
class BrokerCredentials:
    broker_type: str = "mock"  # "mock", "cardinalstone", or "cowrywise"
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    account_number: Optional[str] = None
    cscs_number: Optional[str] = None
    base_url: Optional[str] = None


@dataclass
class BotConfig:
    broker: BrokerCredentials = field(default_factory=BrokerCredentials)
    safety: BotSafetyConfig = field(default_factory=BotSafetyConfig)
    watchlists: Dict[str, TickerStrategyConfig] = field(default_factory=dict)


# Default Sample Configuration Dictionary
DEFAULT_CONFIG_DICT = {
    "broker": {
        "broker_type": "mock",
    },
    "safety": {
        "enable_kill_switch": False,
        "daily_price_limit_pct": 10.0,
        "database_path": "ngx_trading_bot.db",
    },
    "watchlists": {
        "DANGCEM": {
            "x_buy_discount_pct": 4.5,
            "y_profit_target_pct": 8.0,
            "z_capital_budget_naira": 150_000.0,
            "n_cycle_count": 3,
            "entry_fee_pct": 1.5,
            "exit_fee_pct": 1.5,
        },
        "MTNN": {
            "x_buy_discount_pct": 3.5,
            "y_profit_target_pct": 7.5,
            "z_capital_budget_naira": 120_000.0,
            "n_cycle_count": 3,
            "entry_fee_pct": 1.5,
            "exit_fee_pct": 1.5,
        },
        "ACCESSCORP": {
            "x_buy_discount_pct": 5.0,
            "y_profit_target_pct": 10.0,
            "z_capital_budget_naira": 80_000.0,
            "n_cycle_count": 5,
            "entry_fee_pct": 1.5,
            "exit_fee_pct": 1.5,
        },
        "GTCO": {
            "x_buy_discount_pct": 4.0,
            "y_profit_target_pct": 9.0,
            "z_capital_budget_naira": 100_000.0,
            "n_cycle_count": 4,
            "entry_fee_pct": 1.5,
            "exit_fee_pct": 1.5,
        },
    }
}


def load_config(raw_dict: Optional[dict] = None) -> BotConfig:
    data = raw_dict or DEFAULT_CONFIG_DICT
    broker_creds = BrokerCredentials(**data.get("broker", {}))
    safety_conf = BotSafetyConfig(**data.get("safety", {}))

    watchlists: Dict[str, TickerStrategyConfig] = {}
    for symbol, params in data.get("watchlists", {}).items():
        watchlists[symbol] = TickerStrategyConfig(symbol=symbol, **params)

    return BotConfig(broker=broker_creds, safety=safety_conf, watchlists=watchlists)
