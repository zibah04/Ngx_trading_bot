"""
NGX Algorithmic Trading Bot - Production Async Execution Engine
Monitors watchlists concurrently, computes true acquisition costs including fees,
executes discount limit buys, and places net target profit limit sells over N cycles.
"""

import asyncio
import math
import time
import logging
from typing import Any, Dict, Optional, List

from python_bot.broker_base import (
    BaseBroker,
    OrderBook,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
)
from python_bot.config import BotConfig, TickerStrategyConfig
from python_bot.database import TradingDatabase

logger = logging.getLogger("ngx_bot.engine")
PENDING_ORDER_SUBMISSION = "SUBMISSION_PENDING"


class NGXQuantTradingEngine:
    """
    Asynchronous Multi-Stock Algorithmic Trading Engine for the Nigerian Exchange.
    """

    def __init__(
        self,
        config: BotConfig,
        broker: BaseBroker,
        database: Optional[TradingDatabase] = None,
    ):
        self.config = config
        self.broker = broker
        self.db = database or TradingDatabase(config.safety.database_path)
        self.kill_switch_active = config.safety.enable_kill_switch
        self._running = False
        self._worker_tasks: List[asyncio.Task] = []
        self._active_orders_by_symbol: Dict[str, Optional[str]] = {}

    def activate_kill_switch(self, reason: str = "Manual emergency trigger") -> None:
        """Safety kill-switch to pause all trading immediately."""
        self.kill_switch_active = True
        logger.critical("🚨 KILL SWITCH ACTIVATED! Reason: %s. Pausing order submissions.", reason)

    def deactivate_kill_switch(self) -> None:
        """Resume trading after review."""
        self.kill_switch_active = False
        logger.info("✅ Kill switch deactivated. Trading resumed.")

    # -------------------------------------------------------------------------
    # Core Mathematical Formulas (Exact Quant Specification)
    # -------------------------------------------------------------------------
    @staticmethod
    def calculate_buy_price(current_reference_price: float, x_discount_pct: float) -> float:
        """
        Formula: Buy_Price = Current_Price * (1 - X / 100)
        Rounded to standard NGX 2 decimal places (kobo).
        """
        buy_price = current_reference_price * (1.0 - (x_discount_pct / 100.0))
        return round(buy_price, 2)

    @staticmethod
    def calculate_whole_share_quantity(
        z_capital_budget: float,
        buy_price: float,
        entry_fee_pct: float,
    ) -> int:
        """
        Formula: Quantity = floor( Z / (Buy_Price * (1 + Entry_Fee_Pct / 100)) )
        Calculates whole integer shares (no fractional shares allowed on the NGX).
        """
        effective_cost_per_unit = buy_price * (1.0 + (entry_fee_pct / 100.0))
        if effective_cost_per_unit <= 0:
            return 0
        quantity = math.floor(z_capital_budget / effective_cost_per_unit)
        return int(quantity)

    @staticmethod
    def calculate_true_acquisition_cost(
        quantity: int,
        buy_price: float,
        entry_fee_pct: float,
    ) -> tuple[float, float]:
        """
        Calculates:
        1. Total Outlay = (Quantity * Buy_Price) * (1 + Entry_Fee_Pct / 100)
        2. Actual Average Cost per Share = Total Outlay / Quantity
        """
        gross_cost = quantity * buy_price
        total_outlay = round(gross_cost * (1.0 + (entry_fee_pct / 100.0)), 2)
        actual_avg_cost = round(total_outlay / quantity, 4) if quantity > 0 else 0.0
        return total_outlay, actual_avg_cost

    @staticmethod
    def calculate_target_sell_price(
        actual_average_cost: float,
        y_profit_target_pct: float,
        exit_fee_pct: float,
    ) -> float:
        """
        Calculates the gross sell price needed to reach the requested return
        after exit fees, rounded upward to the next kobo.
        """
        fee_rate = exit_fee_pct / 100.0
        if actual_average_cost < 0 or y_profit_target_pct < 0 or not 0 <= fee_rate < 1:
            raise ValueError("Cost and target must be non-negative; exit fee must be below 100%.")
        target_sell = actual_average_cost * (1.0 + (y_profit_target_pct / 100.0)) / (1.0 - fee_rate)
        return math.ceil(target_sell * 100) / 100

    @staticmethod
    def _ensure_recoverable_state(symbol: str, state: Optional[Dict[str, Any]]) -> None:
        if not state:
            return
        if (
            state.get("active_buy_order_id")
            or state.get("active_sell_order_id")
            or state.get("held_quantity", 0) > 0
        ):
            raise RuntimeError(
                f"Cannot safely resume {symbol}: saved state contains an active order or held shares. "
                "Reconcile the broker account before restarting."
            )

    @staticmethod
    def calculate_stop_loss_price(actual_average_cost: float, stop_loss_pct: float) -> float:
        """
        Formula: Stop_Loss_Price = Actual_Average_Cost * (1 - Stop_Loss_Pct / 100)
        Emergency capital defense price to prevent holding falling knives.
        """
        sl_price = actual_average_cost * (1.0 - (stop_loss_pct / 100.0))
        return round(sl_price, 2)

    # -------------------------------------------------------------------------
    # Network Retry Helper with Exponential Backoff
    # -------------------------------------------------------------------------
    async def _execute_with_retry(self, coro_func, *args, retry_safe: bool = True, **kwargs):
        """Retry read-only/idempotent calls, but never blindly repeat submissions."""
        max_attempts = self.config.safety.network_retry_max_attempts
        backoff = self.config.safety.network_retry_backoff_factor
        delay = 1.0

        for attempt in range(1, max_attempts + 1):
            try:
                return await coro_func(*args, **kwargs)
            except Exception as exc:
                if not retry_safe or attempt == max_attempts:
                    logger.error("Operation failed on attempt %d: %s", attempt, exc)
                    raise
                logger.warning(
                    "Network error on attempt %d/%d (%s). Retrying in %.1fs...",
                    attempt, max_attempts, exc, delay
                )
                await asyncio.sleep(delay)
                delay *= backoff

    # -------------------------------------------------------------------------
    # Order Tracking & Verification
    # -------------------------------------------------------------------------
    async def _track_order_until_filled(
        self,
        order_id: str,
        symbol: str,
        polling_interval: float = 1.5,
        timeout_seconds: float = 600.0,
    ) -> OrderResult:
        """
        Monitors order status: SUBMITTED -> PARTIALLY_FILLED -> FILLED.
        Persists state updates to SQLite.
        """
        start_time = time.time()
        while self._running:
            if self.kill_switch_active:
                logger.warning("Kill switch triggered while tracking order %s. Stopping tracking.", order_id)
                break

            order_status = await self._execute_with_retry(self.broker.get_order_status, order_id)

            # Persist order status snapshot
            await self.db.save_order({
                "order_id": order_status.order_id,
                "symbol": order_status.symbol,
                "side": order_status.side.value,
                "order_type": order_status.order_type.value,
                "target_price": order_status.price,
                "quantity": order_status.quantity,
                "filled_quantity": order_status.filled_quantity,
                "average_fill_price": order_status.average_fill_price,
                "status": order_status.status.value,
                "fee_incurred": order_status.fee_incurred,
                "cycle_index": 0,
                "created_at": order_status.created_at,
                "updated_at": order_status.updated_at,
            })

            if order_status.status == OrderStatus.FILLED:
                logger.info(
                    "🎯 Order %s FILLED: %s %d units of %s @ ₦%.2f",
                    order_id, order_status.side.value, order_status.filled_quantity,
                    symbol, order_status.average_fill_price or order_status.price
                )
                return order_status

            if order_status.status in (OrderStatus.CANCELLED, OrderStatus.REJECTED):
                raise RuntimeError(f"Order {order_id} was {order_status.status.value}")

            if order_status.status == OrderStatus.PARTIALLY_FILLED:
                logger.info(
                    "⏳ Order %s PARTIALLY FILLED: %d / %d units of %s",
                    order_id, order_status.filled_quantity, order_status.quantity, symbol
                )

            # Timeout check
            if time.time() - start_time > timeout_seconds:
                logger.warning("⏱️ Order %s timed out after %ds. Cancelling order...", order_id, int(timeout_seconds))
                await self.broker.cancel_order(order_id)
                raise TimeoutError(f"Order {order_id} timed out without full fill.")

            await asyncio.sleep(polling_interval)

        raise RuntimeError(f"Engine stopped while awaiting order {order_id}")

    # -------------------------------------------------------------------------
    # Single Ticker Lifecycle (Repeated N Cycles)
    # -------------------------------------------------------------------------
    async def _run_ticker_worker(self, symbol: str, strat: TickerStrategyConfig) -> None:
        """
        Asynchronously manages the execution lifecycle for one stock:
        Step 1: Liquidity & Order Book Check
        Step 2: Limit Buy Order Calculation
        Step 3: Order Tracking & Fill Verification
        Step 4: True Cost & Target Sell Price Calculation
        Step 5: Cycle Completion & Repeat N times
        """
        logger.info(
            "🚀 Worker started for [%s]: Target Cycles N=%d, Budget Z=₦%s, Discount X=%.1f%%, Target Y=%.1f%%",
            symbol, strat.n_cycle_count, f"{strat.z_capital_budget_naira:,.2f}",
            strat.x_buy_discount_pct, strat.y_profit_target_pct
        )

        # Step 0: Check database for existing state (Crash Recovery)
        saved_state = await self.db.get_ticker_state(symbol)
        self._ensure_recoverable_state(symbol, saved_state)
        start_cycle = 1
        if saved_state:
            start_cycle = saved_state["current_cycle"]
            logger.info("🔄 Resuming [%s] from Cycle %d of %d (recovered from SQLite)", symbol, start_cycle, strat.n_cycle_count)

        cycle = start_cycle
        while self._running and cycle <= strat.n_cycle_count:
            if self.kill_switch_active:
                logger.warning("⏸️ Kill switch active. Stock [%s] worker waiting...", symbol)
                await asyncio.sleep(3.0)
                continue

            logger.info("═══════════════════════════════════════════════════════════════")
            logger.info("▶️ STARTING CYCLE %d of %d for [%s]", cycle, strat.n_cycle_count, symbol)

            # 1. Liquidity & Order Book Check
            try:
                order_book: OrderBook = await self._execute_with_retry(self.broker.get_order_book, symbol)
            except Exception as e:
                logger.error("Failed to fetch order book for %s: %s. Retrying loop...", symbol, e)
                await asyncio.sleep(strat.min_order_interval_seconds)
                continue

            if not order_book.is_liquid:
                logger.warning(
                    "⚠️ [LIQUIDITY CHECK FAILED] %s has empty bids (%d) or empty asks (%d). "
                    "Skipping cycle and retrying on next loop...",
                    symbol, len(order_book.bids), len(order_book.asks)
                )
                await asyncio.sleep(strat.min_order_interval_seconds * 2)
                continue

            current_price = order_book.best_ask or order_book.reference_price
            logger.info(
                "📊 [%s] Order Book Liquid | Ref/Ask Price: ₦%.2f | Best Bid: ₦%.2f | Spread: ₦%.2f",
                symbol, current_price, order_book.best_bid or 0.0, order_book.spread or 0.0
            )

            # 2. Limit Buy Order Calculation
            buy_price = self.calculate_buy_price(current_price, strat.x_buy_discount_pct)
            quantity = self.calculate_whole_share_quantity(
                strat.z_capital_budget_naira, buy_price, strat.entry_fee_pct
            )

            if quantity <= 0:
                logger.error(
                    "❌ [%s] Capital budget Z=₦%.2f is insufficient to buy 1 share at ₦%.2f. Skipping cycle.",
                    symbol, strat.z_capital_budget_naira, buy_price
                )
                await asyncio.sleep(strat.min_order_interval_seconds)
                continue

            est_total_outlay, est_avg_cost = self.calculate_true_acquisition_cost(
                quantity, buy_price, strat.entry_fee_pct
            )

            # Submit the LIMIT_BUY order
            try:
                await self.db.update_ticker_state(
                    symbol=symbol,
                    current_cycle=cycle,
                    target_cycles=strat.n_cycle_count,
                    active_buy_order_id=PENDING_ORDER_SUBMISSION,
                    last_updated=time.time(),
                )
                buy_order = await self._execute_with_retry(
                    self.broker.submit_order,
                    symbol=symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    price=buy_price,
                    quantity=quantity,
                    retry_safe=False,
                )
                logger.info("📤 [%s] Limit Buy Order Submitted: ID=%s", symbol, buy_order.order_id)
            except Exception as e:
                logger.critical("Buy submission for %s is ambiguous; stopping trading for reconciliation: %s", symbol, e)
                self.activate_kill_switch(f"Ambiguous buy submission for {symbol}")
                break

            await self.db.update_ticker_state(
                symbol=symbol,
                current_cycle=cycle,
                target_cycles=strat.n_cycle_count,
                active_buy_order_id=buy_order.order_id,
                last_updated=time.time(),
            )

            # 3. Order Tracking & Fill Verification (BUY)
            try:
                filled_buy = await self._track_order_until_filled(
                    order_id=buy_order.order_id,
                    symbol=symbol,
                    polling_interval=strat.fill_polling_interval_seconds,
                    timeout_seconds=strat.order_timeout_seconds,
                )
            except Exception as e:
                logger.error("Buy order tracking error for %s: %s", symbol, e)
                self.activate_kill_switch(f"Buy order {buy_order.order_id} needs reconciliation")
                break

            exec_buy_price = filled_buy.average_fill_price or buy_price
            exec_quantity = filled_buy.filled_quantity

            # 4. True Cost & Target Sell Price Calculation
            actual_total_outlay, actual_avg_cost = self.calculate_true_acquisition_cost(
                exec_quantity, exec_buy_price, strat.entry_fee_pct
            )

            target_sell_price = self.calculate_target_sell_price(
                actual_avg_cost, strat.y_profit_target_pct, strat.exit_fee_pct
            )

            logger.info(
                "📈 [%s] Buy Executed. True Cost/sh: ₦%.4f. Target Sell: ₦%.2f (Net %.1f%% Profit)",
                symbol, actual_avg_cost, target_sell_price, strat.y_profit_target_pct
            )

            # Submit the LIMIT_SELL order
            try:
                await self.db.update_ticker_state(
                    symbol=symbol,
                    current_cycle=cycle,
                    target_cycles=strat.n_cycle_count,
                    active_sell_order_id=PENDING_ORDER_SUBMISSION,
                    held_quantity=exec_quantity,
                    accumulated_outlay=actual_total_outlay,
                    last_updated=time.time(),
                )
                sell_order = await self._execute_with_retry(
                    self.broker.submit_order,
                    symbol=symbol,
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    price=target_sell_price,
                    quantity=exec_quantity,
                    retry_safe=False,
                )
                logger.info("📤 [%s] Limit Sell Order Submitted: ID=%s", symbol, sell_order.order_id)
            except Exception as e:
                logger.critical("CRITICAL: Failed to submit sell order for %s: %s", symbol, e)
                self.activate_kill_switch(f"Failed to place exit sell order for {symbol}")
                break

            await self.db.update_ticker_state(
                symbol=symbol,
                current_cycle=cycle,
                target_cycles=strat.n_cycle_count,
                active_sell_order_id=sell_order.order_id,
                held_quantity=exec_quantity,
                accumulated_outlay=actual_total_outlay,
                last_updated=time.time(),
            )

            # Track Sell Order until filled
            try:
                filled_sell = await self._track_order_until_filled(
                    order_id=sell_order.order_id,
                    symbol=symbol,
                    polling_interval=strat.fill_polling_interval_seconds,
                    timeout_seconds=strat.order_timeout_seconds,
                )
            except Exception as e:
                logger.error("Sell order tracking error for %s: %s", symbol, e)
                self.activate_kill_switch(f"Sell order {sell_order.order_id} needs reconciliation")
                break

            # 5. Cycle Completion & Multi-Stock Repeat
            exec_sell_price = filled_sell.average_fill_price or target_sell_price
            gross_revenue = exec_quantity * exec_sell_price
            exit_fee = round(gross_revenue * (strat.exit_fee_pct / 100.0), 2)
            entry_fee = round(exec_quantity * exec_buy_price * (strat.entry_fee_pct / 100.0), 2)
            total_fees = entry_fee + exit_fee

            net_revenue = gross_revenue - exit_fee
            net_profit_naira = round(net_revenue - actual_total_outlay, 2)
            net_roi_pct = round((net_profit_naira / actual_total_outlay) * 100.0, 2) if actual_total_outlay > 0 else 0.0

            logger.info("🎉 [CYCLE %d COMPLETE] [%s]", cycle, symbol)
            logger.info(
                "💵 Sold %d shares @ ₦%.2f | Gross: ₦%s | Net Profit: ₦%s (+%.2f%% Net ROI)",
                exec_quantity, exec_sell_price, f"{gross_revenue:,.2f}",
                f"{net_profit_naira:,.2f}", net_roi_pct
            )

            # Record in SQLite
            await self.db.record_completed_cycle({
                "symbol": symbol,
                "cycle_number": cycle,
                "buy_order_id": filled_buy.order_id,
                "sell_order_id": filled_sell.order_id,
                "quantity": exec_quantity,
                "buy_price": exec_buy_price,
                "sell_price": exec_sell_price,
                "total_outlay": actual_total_outlay,
                "gross_revenue": gross_revenue,
                "total_fees": total_fees,
                "net_profit_naira": net_profit_naira,
                "net_roi_pct": net_roi_pct,
                "completed_at": time.time(),
            })

            cycle += 1
            await self.db.update_ticker_state(
                symbol=symbol,
                current_cycle=cycle,
                target_cycles=strat.n_cycle_count,
                active_buy_order_id=None,
                active_sell_order_id=None,
                held_quantity=0,
                accumulated_outlay=0.0,
                is_active=(cycle <= strat.n_cycle_count),
                last_updated=time.time(),
            )

            if cycle <= strat.n_cycle_count:
                await asyncio.sleep(strat.min_order_interval_seconds)

        logger.info("🏁 Stock [%s] finished all %d cycles!", symbol, strat.n_cycle_count)

    async def start(self) -> None:
        """Start concurrently using asyncio.TaskGroup."""
        if self._running:
            raise RuntimeError("Trading engine is already running.")
        self._running = True
        try:
            await self.db.initialize()
            for symbol in self.config.watchlists:
                self._ensure_recoverable_state(symbol, await self.db.get_ticker_state(symbol))

            await self.broker.connect()
            initial_cash = await self.broker.get_cash_balance()
            logger.info("🏦 Connected to Broker. Initial Cash: ₦%s", f"{initial_cash:,.2f}")

            async with asyncio.TaskGroup() as tg:
                for symbol, strat_config in self.config.watchlists.items():
                    task = tg.create_task(
                        self._run_ticker_worker(symbol, strat_config),
                        name=f"worker-{symbol}",
                    )
                    self._worker_tasks.append(task)
        except* Exception as eg:
            logger.error("Exception in worker group: %s", eg.exceptions)
            raise
        finally:
            self._running = False
            self._worker_tasks.clear()
            try:
                await self.broker.disconnect()
            finally:
                await self.db.close()

    async def stop(self) -> None:
        self._running = False
        for task in self._worker_tasks:
            if not task.done():
                task.cancel()
        if self._worker_tasks:
            await asyncio.gather(*self._worker_tasks, return_exceptions=True)
