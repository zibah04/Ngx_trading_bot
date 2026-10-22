import unittest
import tempfile
from pathlib import Path

from bot_engine import NGXQuantTradingEngine
from config import TickerStrategyConfig
from database import TradingDatabase
from main import build_broker
from mock_broker import MockBroker
from python_bot.broker_base import OrderSide, OrderStatus, OrderType


class EngineSafetyTests(unittest.IsolatedAsyncioTestCase):
    def test_sell_price_meets_net_profit_target_after_exit_fee(self):
        cost = 100.0
        target_return = 10.0
        exit_fee = 1.5

        sell_price = NGXQuantTradingEngine.calculate_target_sell_price(
            cost, target_return, exit_fee
        )

        net_proceeds = round(sell_price * (1 - exit_fee / 100), 2)
        required_proceeds = round(cost * (1 + target_return / 100), 2)
        self.assertGreaterEqual(net_proceeds, required_proceeds)

    def test_recovery_rejects_orders_or_held_shares(self):
        states = (
            {"active_buy_order_id": "buy-1", "held_quantity": 0},
            {"active_buy_order_id": "SUBMISSION_PENDING", "held_quantity": 0},
            {"active_sell_order_id": "sell-1", "held_quantity": 0},
            {"active_buy_order_id": None, "active_sell_order_id": None, "held_quantity": 5},
        )

        for state in states:
            with self.subTest(state=state), self.assertRaisesRegex(RuntimeError, "Reconcile"):
                NGXQuantTradingEngine._ensure_recoverable_state("TEST", state)

    def test_recovery_allows_empty_or_completed_state(self):
        NGXQuantTradingEngine._ensure_recoverable_state("TEST", None)
        NGXQuantTradingEngine._ensure_recoverable_state(
            "TEST",
            {
                "active_buy_order_id": None,
                "active_sell_order_id": None,
                "held_quantity": 0,
                "is_active": 0,
            },
        )

    async def test_non_retry_safe_operation_is_attempted_once(self):
        engine = NGXQuantTradingEngine.__new__(NGXQuantTradingEngine)
        engine.config = type(
            "Config",
            (),
            {"safety": type("Safety", (), {"network_retry_max_attempts": 5, "network_retry_backoff_factor": 1.5})()},
        )()
        attempts = 0

        async def fail_once():
            nonlocal attempts
            attempts += 1
            raise OSError("ambiguous network failure")

        with self.assertRaisesRegex(OSError, "ambiguous network failure"):
            await engine._execute_with_retry(fail_once, retry_safe=False)

        self.assertEqual(attempts, 1)

    async def test_mock_broker_tracks_fills_and_prevents_overselling(self):
        broker = MockBroker(initial_cash_naira=10_000.0)
        buy_order = await broker.submit_order(
            "DANGCEM", OrderSide.BUY, OrderType.LIMIT, 100.0, 10
        )

        self.assertEqual(broker.cash_balance, 8_985.0)
        self.assertEqual(broker.portfolio["DANGCEM"], 0)

        broker._apply_fill(buy_order, 5, 1.0)
        self.assertEqual(broker.portfolio["DANGCEM"], 5)
        self.assertEqual(buy_order.status, OrderStatus.PARTIALLY_FILLED)

        broker._apply_fill(buy_order, 10, 2.0)
        self.assertEqual(broker.portfolio["DANGCEM"], 10)
        self.assertEqual(buy_order.status, OrderStatus.FILLED)

        with self.assertRaisesRegex(ValueError, "Insufficient shares"):
            await broker.submit_order(
                "DANGCEM", OrderSide.SELL, OrderType.LIMIT, 120.0, 11
            )

        sell_order = await broker.submit_order(
            "DANGCEM", OrderSide.SELL, OrderType.LIMIT, 120.0, 10
        )
        self.assertEqual(broker.cash_balance, 8_985.0)
        broker._apply_fill(sell_order, 5, 3.0)
        self.assertEqual(broker.cash_balance, 9_576.0)
        self.assertEqual(broker.portfolio["DANGCEM"], 5)

        with self.assertRaisesRegex(ValueError, "Insufficient shares"):
            await broker.submit_order(
                "DANGCEM", OrderSide.SELL, OrderType.LIMIT, 120.0, 1
            )

    def test_strategy_rejects_invalid_values(self):
        with self.assertRaisesRegex(ValueError, "Buy discount"):
            TickerStrategyConfig(symbol="TEST", x_buy_discount_pct=100)
        with self.assertRaisesRegex(ValueError, "Cycle count"):
            TickerStrategyConfig(symbol="TEST", n_cycle_count=0)

    def test_live_broker_requires_explicit_opt_in(self):
        args = type(
            "Args",
            (),
            {
                "enable_live_trading": False,
                "api_key": "key",
                "api_secret": "secret",
                "account": "account",
                "cscs": None,
                "initial_cash": 1000,
            },
        )()
        with self.assertRaisesRegex(ValueError, "Live trading is disabled"):
            build_broker("cardinalstone", args)

    async def test_database_creates_parent_and_preserves_single_connection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nested" / "state.db"
            database = TradingDatabase(str(db_path))
            await database.initialize()
            first_connection = database._conn
            await database.initialize()
            self.assertIs(database._conn, first_connection)

            await database.update_ticker_state(
                symbol="TEST",
                current_cycle=1,
                target_cycles=2,
            )
            state = await database.get_ticker_state("TEST")
            self.assertEqual(state["current_cycle"], 1)
            await database.close()


if __name__ == "__main__":
    unittest.main()