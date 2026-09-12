"""Exercise option persistence without requiring a Home Assistant install."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, AsyncMock

ROOT = Path(__file__).resolve().parents[1] / 'custom_components/technicolor_cga'


def method(class_name, name):
    tree = ast.parse((ROOT / 'config_flow.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    fn = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
    ns = {f'CONF_{key.upper()}': key for key in ('host', 'username', 'password', 'scan_interval', 'force_logout')}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), 'config_flow.py', 'exec'), ns)
    return ns[name]


class OptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_setup_defaults_to_no_takeover(self):
        flow = SimpleNamespace(async_create_entry=Mock())
        fn = method('TechnicolorCGAConfigFlow', 'async_step_user')
        values = dict(host='router', username='user', password='test', scan_interval=300)
        await fn(flow, values)
        self.assertFalse(flow.async_create_entry.call_args.kwargs['options']['force_logout'])
        await fn(flow, dict(values, force_logout=True))
        self.assertTrue(flow.async_create_entry.call_args.kwargs['options']['force_logout'])

    async def test_options_toggle_preserves_other_options_and_reloads(self):
        entry = SimpleNamespace(data={'username': 'user'}, options={'other': 42}, entry_id='test')
        manager = SimpleNamespace(async_update_entry=Mock(), async_reload=AsyncMock())
        flow = SimpleNamespace(_config_entry=entry, hass=SimpleNamespace(config_entries=manager),
                               async_create_entry=Mock())
        fn = method('TechnicolorCGAOptionsFlow', 'async_step_init')
        for enabled in (True, False):
            await fn(flow, dict(host='router', password='test', scan_interval=300, force_logout=enabled))
            options = manager.async_update_entry.call_args.kwargs['options']
            self.assertEqual(options['force_logout'], enabled)
            self.assertEqual(options['other'], 42)
            self.assertEqual(flow.async_create_entry.call_args.kwargs['data'], options)
        self.assertEqual(manager.async_reload.await_count, 2)
