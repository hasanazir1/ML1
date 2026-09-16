"""Real local HTTP startup check; no LLM/RSS calls or user database changes."""
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


class StartupTest(unittest.TestCase):
    def test_run_py_serves_existing_page_and_assets(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            env = {**os.environ, 'DATABASE_PATH': str(Path(folder) / 'startup.db'),
                   'HOST': '127.0.0.1', 'PORT': str(port), 'FLASK_DEBUG': 'False',
                   'SECRET_KEY': 'startup-test-only', 'OPENROUTER_API_KEY': ''}
            process = subprocess.Popen([sys.executable, '-B', 'run.py'], cwd=root, env=env,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT)
            try:
                # Local requests only, ignoring proxy settings inherited from the host.
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                url = f'http://127.0.0.1:{port}'
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        self.fail(process.stdout.read().decode('utf-8', errors='replace'))
                    try:
                        with opener.open(url, timeout=.5) as response:
                            self.assertIn(b'AI Opportunity Agent', response.read())
                            break
                    except (urllib.error.URLError, TimeoutError):
                        time.sleep(.1)
                else:
                    self.fail('Local server did not start')
                with opener.open(url + '/static/js/main.js', timeout=2) as response:
                    self.assertIn(b'initSocket', response.read())
                with opener.open(url + '/socket.io/?EIO=4&transport=polling', timeout=2) as response:
                    self.assertTrue(response.read().startswith(b'0{'))
            finally:
                process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
