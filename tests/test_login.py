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
        with self.assertRaisesRegex(api_module.RouterSessionBusy, 'Existing session left untouched'):
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
        with self.assertRaises(api_module.RouterLoginError) as caught:
            self.api.login()
        self.assertEqual(caught.exception.poll_status, 'login_failed')
        self.assertEqual(self.api.session.post.call_count, 1)

    def test_wifi_nested_envelopes_do_not_trigger_login(self):
        payload = {str(i): {
            "error": "ok", "message": "all values retrieved", "data": {
                "RadioEnable": "true", "OperatingStandards": standards,
                "Channel": channel, "OperatingChannelBandwidth": width,
                "AutoChannelEnable": "true", "SSIDEnable": "true",
                "SSID": "test-network", "BSSID": "00:00:00:00:00:00",
                "ModeEnabled": "WPA2-Personal", "EncryptionMethod": "AES",
                "SSIDAdvertisementEnabled": "true", "RegulatoryDomain": "EU",
            }} for i, standards, channel, width in (
                (1, "b,g,n", "11", "40MHz"), (2, "a,n,ac", "100", "80MHz"))}
        self.api.session.get.return_value = response(payload)
        self.api.login = Mock()
        radios = self.api.wifi()
        self.assertEqual(radios['1']['Channel'], '11')
        self.assertEqual(radios['2']['Channel'], '100')
        self.api.login.assert_not_called()
        self.assertEqual(self.api.session.get.call_count, 1)
        call = self.api.session.get.call_args
        self.assertIn('/api/v1/wifi/1,2/RadioEnable,', call.args[0])
        self.assertEqual(len(call.args[0].split('?_=', 1)[1]), 13)
        self.assertEqual(call.kwargs['timeout'], (5, 15))
        payload['2'] = {'error': 'error'}
        self.assertIsNone(self.api.wifi()['2'])
        self.api.login.assert_not_called()

    def test_wifi_unauthorized_retries_once(self):
        self.api.session.get.side_effect = [
            response({'message': 'Unauthorized!'}),
            response({'1': {'error': 'ok', 'data': {'RadioEnable': 'false'}}}),
        ]
        self.api.login = Mock()
        self.assertEqual(self.api.wifi()['1']['RadioEnable'], 'false')
        self.api.login.assert_called_once()
        self.assertEqual(self.api.session.get.call_count, 2)

    def test_wifi_invalid_response_is_not_mistaken_for_expired_login(self):
        self.api.login = Mock()
        for payload in (None, [], {}, {'error': 'unsupported'}):
            self.api.session.get.return_value = response(payload)
            with self.assertRaises(ValueError):
                self.api.wifi()
        self.api.login.assert_not_called()


if __name__ == '__main__':
    unittest.main()
