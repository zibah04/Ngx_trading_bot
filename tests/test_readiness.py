import asyncio
import sqlite3
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

from bot_engine import NGXQuantTradingEngine
from broker_base import OrderBook, OrderBookLevel, OrderSide, OrderStatus, OrderType
from config import BotConfig, BotSafetyConfig, TickerStrategyConfig
from database import TradingDatabase
from mock_broker import MockBroker
from scripts.state_tools import backup, report
from simulation_runtime import SimulationRuntime
from instance_lock import InstanceLock


def config(path=':memory:'):
    return BotConfig(safety=BotSafetyConfig(database_path=path, cancellation_timeout_seconds=0.15),
                     watchlists={'DANGCEM': TickerStrategyConfig(
                         'DANGCEM', n_cycle_count=1, fill_polling_interval_seconds=0.01)})


def book():
    return OrderBook('DANGCEM', [OrderBookLevel(749, 1000)], [OrderBookLevel(751, 1000)],
                     750, time.time(), previous_close_price=750)


class ImmediateBroker(MockBroker):
    async def connect(self):
        pass

    async def submit_order(self, *args, **kwargs):
        order = await super().submit_order(*args, **kwargs)
        self._apply_fill(order, order.quantity, time.time())
        return order


class TradingReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_cycle_records_profit_and_clean_state(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / 'state.db')
            broker = ImmediateBroker()
            engine = NGXQuantTradingEngine(config(path), broker)
            await asyncio.wait_for(engine.start(), timeout=2)
            with sqlite3.connect(path) as conn:
                cycle = conn.execute('SELECT quantity, net_profit_naira, net_roi_pct FROM completed_cycles').fetchone()
                self.assertGreater(cycle[0], 0)
                self.assertGreater(cycle[1], 0)
                self.assertGreaterEqual(cycle[2], 10)
                state = conn.execute('SELECT current_cycle, active_buy_order_id, active_sell_order_id, held_quantity FROM ticker_states').fetchone()
                self.assertEqual(state, (2, None, None, 0))
            self.assertEqual(broker.portfolio['DANGCEM'], 0)
            cash = broker.cash_balance
            await engine.start()
            self.assertEqual(broker.cash_balance, cash)  # Completed cycles never run twice.

    def test_unsafe_market_data_is_rejected(self):
        engine = NGXQuantTradingEngine(config(), MockBroker())
        engine.validate_order_book('DANGCEM', book())
        changes = [
            {'timestamp': time.time() - 60}, {'timestamp': float('nan')},
            {'timestamp': time.time() + 60}, {'previous_close_price': None},
            {'previous_close_price': 1}, {'reference_price': float('inf')},
            {'bids': [OrderBookLevel(800, 100)]},
            {'bids': [OrderBookLevel(600, 100)]},
            {'asks': [OrderBookLevel(float('nan'), 100)]},
            {'asks': [OrderBookLevel(751, 0)]}, {'symbol': 'WRONG'},
        ]
        for change in changes:
            with self.subTest(change=change):
                bad = book()
                for key, value in change.items():
                    setattr(bad, key, value)
                with self.assertRaises(ValueError):
                    engine.validate_order_book('DANGCEM', bad)

    async def test_capital_limit_prevents_any_order(self):
        cfg = config()
        cfg.safety.max_total_budget_naira = 100
        broker = ImmediateBroker()
        engine = NGXQuantTradingEngine(cfg, broker)
        with self.assertRaises(ExceptionGroup):
            await engine.start()
        self.assertFalse(broker.active_orders)
        self.assertFalse(engine._running)

    async def test_halt_during_balance_request_prevents_submission(self):
        broker = MockBroker()
        engine = NGXQuantTradingEngine(config(), broker)
        engine._running = True
        async def halt_and_balance():
            engine.activate_kill_switch('test halt')
            return 2_000_000
        broker.get_cash_balance = halt_and_balance
        with self.assertRaisesRegex(RuntimeError, 'halted'):
            await engine._submit_checked_order(symbol='DANGCEM', side=OrderSide.BUY,
                                                order_type=OrderType.LIMIT, price=100, quantity=1)
        self.assertFalse(broker.active_orders)

    async def test_halt_during_quote_request_prevents_submission(self):
        broker = MockBroker()
        engine = NGXQuantTradingEngine(config(), broker)
        engine._running = True
        async def halt_and_quote(symbol):
            engine.activate_kill_switch('halt during quote')
            return book()
        broker.get_order_book = halt_and_quote
        with self.assertRaisesRegex(RuntimeError, 'halted'):
            await engine._submit_checked_order(symbol='DANGCEM', side=OrderSide.BUY,
                                                order_type=OrderType.LIMIT, price=750, quantity=1)
        self.assertFalse(broker.active_orders)

    async def test_invalid_broker_fill_cannot_be_recorded_as_success(self):
        broker = MockBroker()
        engine = NGXQuantTradingEngine(config(), broker)
        engine._running = True
        order = await broker.submit_order('DANGCEM', OrderSide.BUY, OrderType.LIMIT, 750, 10)
        bad = replace(order, status=OrderStatus.FILLED, filled_quantity=0)
        broker.get_order_status = AsyncMock(return_value=bad)
        with self.assertRaisesRegex(ValueError, 'invalid fill'):
            await engine._track_order_until_filled(order.order_id, 'DANGCEM')
        self.assertIsNone(engine.db._conn)

    async def test_delayed_failure_does_not_mark_new_simulation_failed(self):
        runtime = SimulationRuntime.__new__(SimulationRuntime)
        runtime.task = None
        runtime.error = None
        async def fail():
            raise RuntimeError('old simulation error')
        old_task = asyncio.create_task(fail())
        try:
            await old_task
        except RuntimeError:
            pass
        with self.assertLogs('simulation_runtime', level='ERROR'):
            runtime._finished(old_task)
        self.assertIsNone(runtime.error)

    async def test_shutdown_confirms_cancellation_before_disconnect(self):
        with tempfile.TemporaryDirectory() as d:
            broker = MockBroker()
            broker.reference_prices['DANGCEM'] = 750
            engine = NGXQuantTradingEngine(config(str(Path(d) / 'state.db')), broker)
            task = asyncio.create_task(engine.start())
            for _ in range(100):
                if engine._active_orders_by_symbol:
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(engine._active_orders_by_symbol)
            await engine.stop()
            await asyncio.wait_for(task, 2)
            self.assertTrue(all(o.status == OrderStatus.CANCELLED for o in broker.active_orders.values()))
            self.assertEqual(broker.cash_balance, 2_000_000)
            self.assertFalse(engine._active_orders_by_symbol)
            self.assertFalse(broker._connected)
            # State is retained for reconciliation, not silently cleared.
            with sqlite3.connect(engine.db.db_path) as conn:
                self.assertIsNotNone(conn.execute('SELECT active_buy_order_id FROM ticker_states').fetchone()[0])

    async def test_timeout_preserves_partial_fill_and_confirms_cancellation(self):
        broker = MockBroker(initial_cash_naira=10_000)
        engine = NGXQuantTradingEngine(config(), broker)
        engine._running = True
        order = await broker.submit_order('DANGCEM', OrderSide.BUY, OrderType.LIMIT, 100, 10)
        broker._apply_fill(order, 5, time.time())
        engine._active_orders_by_symbol['DANGCEM'] = order.order_id
        try:
            with self.assertRaises(TimeoutError):
                await engine._track_order_until_filled(order.order_id, 'DANGCEM', 0.001, 0.001)
            self.assertEqual(order.status, OrderStatus.CANCELLED)
            self.assertEqual(order.filled_quantity, 5)
            self.assertEqual(broker.portfolio['DANGCEM'], 5)
            self.assertAlmostEqual(broker.cash_balance, 9492.5)
        finally:
            await engine.db.close()

    async def test_cancellation_ack_without_terminal_status_is_failure(self):
        broker = MockBroker()
        engine = NGXQuantTradingEngine(config(), broker)
        order = await broker.submit_order('DANGCEM', OrderSide.BUY, OrderType.LIMIT, 100, 10)
        engine._active_orders_by_symbol['DANGCEM'] = order.order_id
        broker.cancel_order = AsyncMock(return_value=True)
        with self.assertRaisesRegex(RuntimeError, 'Unconfirmed cancellation'):
            await engine._cancel_known_orders()
        self.assertEqual(engine._active_orders_by_symbol['DANGCEM'], order.order_id)
        self.assertTrue(engine.kill_switch_active)

    async def test_fill_during_timeout_cancellation_is_not_lost(self):
        broker = MockBroker()
        engine = NGXQuantTradingEngine(config(), broker)
        engine._running = True
        order = await broker.submit_order('DANGCEM', OrderSide.BUY, OrderType.LIMIT, 100, 10)
        async def fill_instead_of_cancel(order_id):
            broker._apply_fill(order, 10, time.time())
            return False
        broker.cancel_order = fill_instead_of_cancel
        try:
            result = await engine._track_order_until_filled(order.order_id, 'DANGCEM', 0.001, 0.001)
            self.assertEqual(result.status, OrderStatus.FILLED)
            self.assertEqual(result.filled_quantity, 10)
        finally:
            await engine.db.close()

    async def test_kill_switch_cancels_tracked_order(self):
        broker = MockBroker()
        engine = NGXQuantTradingEngine(config(), broker)
        engine._running = True
        order = await broker.submit_order('DANGCEM', OrderSide.BUY, OrderType.LIMIT, 100, 10)
        engine.activate_kill_switch('test')
        try:
            with self.assertRaises(RuntimeError):
                await engine._track_order_until_filled(order.order_id, 'DANGCEM')
            self.assertEqual(order.status, OrderStatus.CANCELLED)
        finally:
            await engine.db.close()

    def test_non_finite_config_is_rejected(self):
        with self.assertRaises(ValueError):
            TickerStrategyConfig('DANGCEM', z_capital_budget_naira=float('nan'))
        with self.assertRaises(ValueError):
            BotSafetyConfig(max_total_budget_naira=float('inf'))


class SimulationAndStateTests(unittest.TestCase):
    def test_second_engine_cannot_own_same_database(self):
        with tempfile.TemporaryDirectory() as d:
            first = InstanceLock(str(Path(d) / 'state.db'))
            second = InstanceLock(str(Path(d) / 'state.db'))
            try:
                first.acquire()
                with self.assertRaisesRegex(RuntimeError, 'Another engine'):
                    second.acquire()
                first.release()
                second.acquire()
            finally:
                first.release()
                second.release()

    def test_simulation_controls_are_serialized_and_archive_runs(self):
        with tempfile.TemporaryDirectory() as d:
            runtime = SimulationRuntime(str(Path(d) / 'simulation.db'))
            try:
                first = runtime.call('start')
                engine = runtime.engine
                runtime.call('start')
                runtime.call('new')
                self.assertIs(runtime.engine, engine)
                deadline = time.monotonic() + 3
                while not runtime.engine._active_orders_by_symbol and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(runtime.engine._active_orders_by_symbol)
                runtime.call('stop')
                while runtime.call('snapshot')['busy'] and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertFalse(runtime.call('snapshot')['busy'])
                self.assertTrue(Path(d, first['session']).exists())
                runtime.call('new')
                second = runtime.call('snapshot')
                self.assertNotEqual(first['session'], second['session'])
                self.assertEqual(second['status'], 'Stopped')
                self.assertTrue(Path(d, first['session']).exists())
            finally:
                runtime.close()

    def test_backup_report_and_restore_preserve_state(self):
        with tempfile.TemporaryDirectory() as d:
            source, destination = Path(d) / 'source.db', Path(d) / 'backup.db'
            async def create_state():
                db = TradingDatabase(str(source))
                await db.initialize()
                await db.update_ticker_state('DANGCEM', 1, 3, active_buy_order_id='SUBMISSION_PENDING')
                await db.close()
            asyncio.run(create_state())
            backup(source, destination)
            self.assertEqual(report(source), report(destination))
            self.assertEqual(report(destination)['integrity'], 'ok')
            self.assertEqual(report(destination)['ticker_states'][0]['active_buy_order_id'], 'SUBMISSION_PENDING')
            with self.assertRaises(FileExistsError):
                backup(source, destination)
            with self.assertRaises(FileNotFoundError):
                report(Path(d) / 'missing.db')
            self.assertFalse((Path(d) / 'missing.db').exists())
