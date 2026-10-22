"""One process-wide simulation, controlled exclusively on its asyncio loop."""
import asyncio
import copy
import logging
import threading
import uuid
from pathlib import Path

from bot_engine import NGXQuantTradingEngine
from config import DEFAULT_CONFIG_DICT, load_config
from database import TradingDatabase
from mock_broker import MockBroker

logger = logging.getLogger(__name__)


class SimulationRuntime:
    def __init__(self, database_path: str):
        self.database_path = Path(database_path)
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.task = None
        self.stop_task = None
        self.error = None
        self._new_engine()

    def _new_engine(self):
        config = load_config(copy.deepcopy(DEFAULT_CONFIG_DICT))
        # The mock broker is in memory. Never pair a new broker with old orders.
        session_id = uuid.uuid4().hex
        self.session_path = self.database_path.with_name(
            f"{self.database_path.stem}-{session_id}.db"
        )
        config.safety.database_path = str(self.session_path)
        self.engine = NGXQuantTradingEngine(
            config, MockBroker(), TradingDatabase(str(self.session_path))
        )
        self.error = None

    def call(self, action: str):
        return asyncio.run_coroutine_threadsafe(self._dispatch(action), self.loop).result(timeout=10)

    async def _dispatch(self, action):
        busy = self.task is not None and not self.task.done()
        stopping = self.stop_task is not None and not self.stop_task.done()
        if action == 'start' and not busy and not stopping:
            self.error = None
            self.task = asyncio.create_task(self.engine.start())
            self.task.add_done_callback(self._finished)
        elif action == 'stop' and busy and not stopping:
            self.stop_task = asyncio.create_task(self._stop())
        elif action == 'new' and not busy and not stopping:
            self._new_engine()
            self.task = None
        elif action != 'snapshot':
            if action not in ('start', 'stop', 'new'):
                raise ValueError('Unknown simulation action')
        return self._snapshot()

    def _finished(self, task):
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            if task is self.task:
                # A completed run must not overwrite a newer simulation's status.
                self.error = str(exc)
            logger.exception('Simulation failed')

    async def _stop(self):
        await self.engine.stop()
        try:
            await self.task
        except Exception:
            # _finished retains the engine error for the dashboard.
            pass

    def _snapshot(self):
        busy = self.task is not None and not self.task.done()
        stopping = self.stop_task is not None and not self.stop_task.done()
        error = self.error or self.engine.last_error
        status = ('Stopping' if stopping else 'Blocked' if self.engine.kill_switch_active
                  else 'Error' if error else 'Running' if busy else 'Stopped')
        return {'status': status, 'busy': busy or stopping,
                'cash': self.engine.broker.cash_balance, 'error': error,
                'session': self.session_path.name,
                'watchlists': self.engine.config.watchlists}

    def close(self):
        if self.loop.is_closed():
            return
        async def shutdown():
            if self.stop_task is not None and not self.stop_task.done():
                await self.stop_task
            elif self.task is not None and not self.task.done():
                await self._stop()
        asyncio.run_coroutine_threadsafe(shutdown(), self.loop).result(timeout=60)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)
        self.loop.close()
