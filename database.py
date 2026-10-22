"""
NGX Algorithmic Trading Bot - SQLite State Persistence Engine
Uses asynchronous aiosqlite to record orders, active trades, and cycle history.
"""

import aiosqlite
import logging
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger("ngx_bot.database")


class TradingDatabase:
    def __init__(self, db_path: str = "ngx_trading_bot.db"):
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> None:
        if self._conn is not None:
            return
        if self.db_path != ":memory:":
            Path(self.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path, timeout=30)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA busy_timeout = 5000")

        async with self._conn.cursor() as cursor:
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    target_price REAL NOT NULL,
                    quantity INTEGER NOT NULL,
                    filled_quantity INTEGER DEFAULT 0,
                    average_fill_price REAL DEFAULT 0.0,
                    status TEXT NOT NULL,
                    fee_incurred REAL DEFAULT 0.0,
                    cycle_index INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            await cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol)")

            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS completed_cycles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    cycle_number INTEGER NOT NULL,
                    buy_order_id TEXT NOT NULL,
                    sell_order_id TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    buy_price REAL NOT NULL,
                    sell_price REAL NOT NULL,
                    total_outlay REAL NOT NULL,
                    gross_revenue REAL NOT NULL,
                    total_fees REAL NOT NULL,
                    net_profit_naira REAL NOT NULL,
                    net_roi_pct REAL NOT NULL,
                    completed_at REAL NOT NULL
                )
            """)

            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS ticker_states (
                    symbol TEXT PRIMARY KEY,
                    current_cycle INTEGER DEFAULT 1,
                    target_cycles INTEGER NOT NULL,
                    active_buy_order_id TEXT,
                    active_sell_order_id TEXT,
                    held_quantity INTEGER DEFAULT 0,
                    accumulated_outlay REAL DEFAULT 0.0,
                    is_active INTEGER DEFAULT 1,
                    last_updated REAL NOT NULL
                )
            """)
            await self._conn.commit()

    async def _get_connection(self) -> aiosqlite.Connection:
        if self._conn is None:
            await self.initialize()
        if self._conn is None:
            raise RuntimeError("Database connection could not be initialized.")
        return self._conn

    async def save_order(self, order_data: Dict[str, Any]) -> None:
        conn = await self._get_connection()

        query = """
            INSERT INTO orders (
                order_id, symbol, side, order_type, target_price,
                quantity, filled_quantity, average_fill_price, status,
                fee_incurred, cycle_index, created_at, updated_at
            ) VALUES (
                :order_id, :symbol, :side, :order_type, :target_price,
                :quantity, :filled_quantity, :average_fill_price, :status,
                :fee_incurred, :cycle_index, :created_at, :updated_at
            )
            ON CONFLICT(order_id) DO UPDATE SET
                filled_quantity = excluded.filled_quantity,
                average_fill_price = excluded.average_fill_price,
                status = excluded.status,
                fee_incurred = excluded.fee_incurred,
                updated_at = excluded.updated_at
        """
        async with conn.execute(query, order_data):
            await conn.commit()

    async def record_completed_cycle(self, cycle_record: Dict[str, Any]) -> None:
        conn = await self._get_connection()

        query = """
            INSERT INTO completed_cycles (
                symbol, cycle_number, buy_order_id, sell_order_id,
                quantity, buy_price, sell_price, total_outlay,
                gross_revenue, total_fees, net_profit_naira, net_roi_pct,
                completed_at
            ) VALUES (
                :symbol, :cycle_number, :buy_order_id, :sell_order_id,
                :quantity, :buy_price, :sell_price, :total_outlay,
                :gross_revenue, :total_fees, :net_profit_naira, :net_roi_pct,
                :completed_at
            )
        """
        async with conn.execute(query, cycle_record):
            await conn.commit()

    async def get_ticker_state(self, symbol: str) -> Optional[Dict[str, Any]]:
        conn = await self._get_connection()

        query = "SELECT * FROM ticker_states WHERE symbol = ?"
        async with conn.execute(query, (symbol,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
        return None

    async def update_ticker_state(
        self,
        symbol: str,
        current_cycle: int,
        target_cycles: int,
        active_buy_order_id: Optional[str] = None,
        active_sell_order_id: Optional[str] = None,
        held_quantity: int = 0,
        accumulated_outlay: float = 0.0,
        is_active: bool = True,
        timestamp: float = 0.0,
        last_updated: Optional[float] = None,
    ) -> None:
        conn = await self._get_connection()

        ts = last_updated if last_updated is not None else timestamp
        if ts == 0.0:
            ts = time.time()

        query = """
            INSERT INTO ticker_states (
                symbol, current_cycle, target_cycles, active_buy_order_id,
                active_sell_order_id, held_quantity, accumulated_outlay,
                is_active, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                current_cycle = excluded.current_cycle,
                target_cycles = excluded.target_cycles,
                active_buy_order_id = excluded.active_buy_order_id,
                active_sell_order_id = excluded.active_sell_order_id,
                held_quantity = excluded.held_quantity,
                accumulated_outlay = excluded.accumulated_outlay,
                is_active = excluded.is_active,
                last_updated = excluded.last_updated
        """
        await conn.execute(
            query,
            (
                symbol, current_cycle, target_cycles, active_buy_order_id,
                active_sell_order_id, held_quantity, accumulated_outlay,
                1 if is_active else 0, ts,
            ),
        )
        await conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None
            
