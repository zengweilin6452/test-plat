"""Isolated deployment checks. Run: python scripts/test_deployment_isolation.py."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
from app.deployment import is_formal_database


class DeploymentTests(unittest.TestCase):
    def test_database_identity(self):
        for url in (
            'postgresql+psycopg://other:pass@127.0.0.1:55432/testdock?application_name=x',
            'postgresql://other@LOCALHOST.:55432/testdock',
            'postgresql://other@[::1]:55432/testdock',
            'postgresql://other@127.0.0.1:55432/%74estdock',
            'postgresql://other@elsewhere/demo?host=127.0.0.1&port=55432&dbname=testdock',
        ):
            self.assertTrue(is_formal_database(url), url)
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/seed_demo.py'), '--demo', '--dry-run', '--database-url', url], capture_output=True)
            self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(is_formal_database('postgresql://testdock@localhost:55433/testdock_demo'))

    def test_root_env_and_startup(self):
        with tempfile.TemporaryDirectory(prefix='testdock deployment ') as temp:
            root = Path(temp)
            for name in ('config.py', 'deployment.py'):
                (root / 'server/app').mkdir(parents=True, exist_ok=True)
                shutil.copy(ROOT / 'server/app' / name, root / 'server/app' / name)
            (root / 'scripts').mkdir()
            for name in ('deployment_env.py', 'load_env.ps1', 'dev_up.ps1', 'dev_down.ps1'):
                shutil.copy(ROOT / 'scripts' / name, root / 'scripts' / name)
            (root / '.env').write_text('TESTDOCK_PORT=18761\nTESTDOCK_API_PORT=18762\nTESTDOCK_DEMO_MODE=1\n', encoding='utf-8')
            env = {k: v for k, v in os.environ.items() if not k.startswith('TESTDOCK_')}
            env['PYTHONUTF8'] = '1'
            def call(*args):
                return subprocess.run([sys.executable, str(root / 'scripts/deployment_env.py'), *args], env=env, cwd=temp, capture_output=True, text=True, encoding='utf-8')
            result = call()
            self.assertEqual(json.loads(result.stdout)['TESTDOCK_PORT'], '18761')
            def settings_port():
                code = 'import sys;sys.path.insert(0, ' + repr(str(root / 'server')) + ');from app.config import settings;print(settings.port)'
                return subprocess.check_output([sys.executable, '-c', code], env=env, cwd=temp, text=True).strip()
            self.assertEqual(settings_port(), '18761')
            env['TESTDOCK_PORT'] = '18763'
            self.assertEqual(json.loads(call().stdout)['TESTDOCK_PORT'], '18763')
            self.assertEqual(settings_port(), '18763')
            self.assertEqual(call('--validate-demo').returncode, 2)
            env['TESTDOCK_DATABASE_URL'] = 'postgresql://testdock@localhost:55433/testdock_demo'
            self.assertEqual(call('--validate-demo').returncode, 2)
            env['TESTDOCK_DATA_DIR'] = 'demo-data'
            self.assertEqual(call('--validate-demo').returncode, 0)
            env['TESTDOCK_RUNTIME_DIR'] = 'runtime'
            # A real occupied Windows port must fail before any API is started.
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                listener.listen()
                env['TESTDOCK_WEB_PORT'] = str(listener.getsockname()[1])
                result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(root / 'scripts/dev_up.ps1')], env=env, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root / 'runtime/backend.pid').exists())
                self.assertFalse((root / 'runtime/frontend.pid').exists())
            # The stop script reads the same root .env/runtime without touching services.
            result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(root / 'scripts/dev_down.ps1'), '-KeepPg'], env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
