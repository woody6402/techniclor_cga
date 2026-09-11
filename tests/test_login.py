"""Login must never evict another router session."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock

path = Path(__file__).resolve().parents[1] / 'custom_components/technicolor_cga/technicolor_cga.py'
spec = importlib.util.spec_from_file_location('router_api', path)
api_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api_module)


def response(data):
    return Mock(json=Mock(return_value=data))


class LoginTests(unittest.TestCase):
    def setUp(self):
        self.api = api_module.TechnicolorCGA('user', 'password')
        self.api.session = Mock()
        self.api.session.cookies = {'auth': 'test-token'}

    def test_busy_session_is_not_evicted_then_recovers(self):
        self.api.logged = True
        self.api.session.post.return_value = response({'message': 'MSG_LOGIN_150'})
        with self.assertRaisesRegex(RuntimeError, 'Existing session left untouched'):
            self.api.login()
        self.assertFalse(self.api.logged)
        self.assertEqual(self.api.session.post.call_count, 1)
        self.assertEqual(self.api.session.post.call_args.kwargs['data']['logout'], 'false')
        self.api.session.post.side_effect = [
            response({'salt': 'a', 'saltwebui': 'b'}), response({'error': 'ok'})]
        self.assertTrue(self.api.login())
        for call in self.api.session.post.call_args_list:
            self.assertEqual(call.kwargs['data']['logout'], 'false')
            self.assertEqual(call.kwargs['timeout'], (5, 15))

    def test_expired_ha_session_does_not_retry_data_if_browser_busy(self):
        self.api.session.get.return_value = response({'message': 'Unauthorized!'})
        self.api.session.post.return_value = response({'message': 'MSG_LOGIN_150'})
        with self.assertRaises(RuntimeError):
            self.api.call('data-endpoint')
        self.assertEqual(self.api.session.get.call_count, 2)  # Data, then session/menu.
        self.assertEqual(self.api.session.post.call_count, 1)

    def test_incomplete_challenge_does_not_submit_password(self):
        self.api.session.post.return_value = response({'salt': 'a'})
        with self.assertRaises(RuntimeError):
            self.api.login()
        self.assertEqual(self.api.session.post.call_count, 1)


if __name__ == '__main__':
    unittest.main()
