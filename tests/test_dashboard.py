import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class DashboardTests(unittest.TestCase):
    def test_dashboard_start_stop_blocked_status_and_new_simulation(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'NGX_DATABASE_PATH': str(Path(d) / 'dashboard.db')}):
            source = Path('ui_app.py').read_text() + "\nst.session_state['_test_runtime'] = runtime\n"
            app = AppTest.from_string(source).run(timeout=20)
            runtime = app.session_state['_test_runtime']
            try:
                self.assertFalse(app.exception)
                self.assertEqual(app.metric[1].value, '₦2,000,000.00')
                self.assertEqual(app.metric[2].value, 'Stopped')
                app.button[0].click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.metric[2].value, 'Running')

                async def halt():
                    runtime.engine.activate_kill_switch('Test market-data failure')
                asyncio.run_coroutine_threadsafe(halt(), runtime.loop).result(timeout=5)
                app.run()
                self.assertEqual(app.metric[2].value, 'Blocked')
                self.assertIn('market-data failure', app.error[0].value)
                self.assertTrue(app.button[0].disabled)
                app.button[1].click().run()
                deadline = time.monotonic() + 5
                while runtime.call('snapshot')['busy'] and time.monotonic() < deadline:
                    time.sleep(.01)
                old_session = runtime.call('snapshot')['session']
                app.run()
                app.button[2].click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.metric[2].value, 'Stopped')
                self.assertNotEqual(runtime.call('snapshot')['session'], old_session)
            finally:
                runtime.close()
                runtime.close()  # Process shutdown callbacks are safe after explicit cleanup.
