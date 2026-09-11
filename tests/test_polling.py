"""Isolated integration tests using a minimal Home Assistant API stand-in.

Run: python3 -m unittest discover -s tests -v
No router or Home Assistant installation is required.
"""
import asyncio
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1] / 'custom_components' / 'technicolor_cga'


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Entity:
    def async_write_ha_state(self):
        self.writes = getattr(self, 'writes', 0) + 1


def load_sensors():
    modules = {}
    for name in ('homeassistant', 'homeassistant.const', 'homeassistant.components',
                 'homeassistant.components.sensor', 'homeassistant.helpers',
                 'homeassistant.helpers.event', 'homeassistant.helpers.entity', 'cga_test'):
        modules[name] = ModuleType(name)
    const = modules['homeassistant.const']
    for key in ('HOST', 'SCAN_INTERVAL'):
        setattr(const, 'CONF_' + key, key.lower())
    const.UnitOfInformation = SimpleNamespace(BYTES='B')
    sensor = modules['homeassistant.components.sensor']
    sensor.SensorEntity = Entity
    sensor.SensorStateClass = SimpleNamespace(MEASUREMENT='measurement', TOTAL_INCREASING='total_increasing')
    sensor.SensorDeviceClass = SimpleNamespace(DATA_SIZE='data_size')
    modules['homeassistant.helpers.entity'].EntityCategory = SimpleNamespace(DIAGNOSTIC='diagnostic')
    modules['homeassistant.helpers.event'].async_track_time_interval = Mock()
    modules['cga_test.const'] = ModuleType('cga_test.const')
    modules['cga_test.const'].DOMAIN = 'technicolor_cga'
    modules['cga_test.polling'] = load('polling', 'polling.py')
    with patch.dict(sys.modules, modules):
        return load('cga_test.sensor', 'sensor.py')


sensor = load_sensors()
RouterPoller = sensor.RouterPoller


def make_api():
    row = {'LockStatus': 'Locked', 'PowerLevel': '2 dBmV', 'SNRLevel': '41 dB'}
    return SimpleNamespace(
        system=Mock(return_value={'CMStatus': 'OPERATIONAL'}),
        dhcp=Mock(return_value={'IPAddressGW': '192.168.0.1', 'PoolEnable': True}),
        aDev=Mock(return_value={'hostTbl': [{'physaddress': 'aa', 'ipaddress': '192.168.0.2', 'active': 'true'}]}),
        levels=Mock(return_value={'DSTbl': [row, dict(row, LockStatus='Unlocked', PowerLevel='99 dBmV', SNRLevel='0 dB')], 'USTbl': [row], 'ErrTbl': [{'Correcteds': '3', 'Uncorrectables': '0'}]}),
        interfaces=Mock(return_value={'WANEthernet': {'Status': 'Up'}, 'WANStats': {k: '10' for k in ('PacketsReceived','PacketsSent','BytesReceived','BytesSent','ErrorsReceived','ErrorsSent')}, 'LANEtherTable': [{'Status': 'Up'}]}),
    )


def executor(fn):
    return asyncio.get_running_loop().run_in_executor(None, fn)


class PollingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.api = make_api()
        self.hass = SimpleNamespace(async_add_executor_job=executor,
                                    data={'technicolor_cga': {'test': {'api': self.api}}})
        self.poller = RouterPoller(self.hass, self.api)

    async def test_round_counts_failure_recovery(self):
        await self.poller.async_refresh()
        for fn in vars(self.api).values():
            self.assertEqual(fn.call_count, 1)
        self.api.levels.assert_called_once_with(max_age=0)
        self.api.interfaces.assert_called_once_with(max_age=0)
        self.api.dhcp.side_effect = TimeoutError('offline')
        await self.poller.async_refresh()
        self.assertEqual(set(self.poller.data), {'system'})
        self.assertEqual(self.api.aDev.call_count, 1)
        self.api.dhcp.side_effect = None
        await self.poller.async_refresh()
        self.assertEqual(len(self.poller.data), 5)

    async def test_stop_and_overlap(self):
        pending = asyncio.get_running_loop().create_future()
        self.hass.async_add_executor_job = Mock(return_value=pending)
        task = asyncio.create_task(self.poller.async_refresh())
        await asyncio.sleep(0)
        self.assertFalse(await self.poller.async_refresh())
        stop = asyncio.create_task(self.poller.async_stop())
        await asyncio.sleep(0)
        self.assertFalse(stop.done())
        pending.set_result({'CMStatus': 'OPERATIONAL'})
        self.assertFalse(await task)
        await stop
        self.assertEqual(self.hass.async_add_executor_job.call_count, 1)
        self.assertFalse(await self.poller.async_refresh())
        self.assertEqual(self.poller.data, {})

    async def test_cancel_drains_inflight_request(self):
        pending = asyncio.get_running_loop().create_future()
        self.hass.async_add_executor_job = Mock(return_value=pending)
        task = asyncio.create_task(self.poller.async_refresh())
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        self.assertFalse(pending.cancelled())
        self.assertFalse(task.done())
        pending.set_result({'CMStatus': 'OPERATIONAL'})
        with self.assertRaises(asyncio.CancelledError):
            await task
        await self.poller.async_stop()
        self.assertEqual(self.hass.async_add_executor_job.call_count, 1)

    async def test_setup_entities_and_late_dhcp(self):
        self.api.dhcp.side_effect = TimeoutError('offline')
        entry = SimpleNamespace(entry_id='test', options={}, data={})
        entities = []
        timer = Mock(return_value=Mock())
        with patch.object(sensor, 'async_track_time_interval', timer):
            await sensor.async_setup_entry(self.hass, entry, lambda items, **kw: entities.extend(items))
            self.assertEqual(len(entities), 17)
            self.assertTrue(entities[0]._attr_available)
            self.assertFalse(entities[1]._attr_available)
            self.api.dhcp.side_effect = None
            tick = timer.call_args.args[1]
            await tick(None)
            self.assertEqual(len(entities), 19)
            self.assertTrue(all(e._attr_available for e in entities))
            self.assertEqual(self.api.dhcp.call_count, 2)
            self.assertEqual(self.api.aDev.call_count, 1)
            self.assertEqual(self.api.interfaces.call_count, 1)
            by_suffix = {e._attr_unique_id.removeprefix('test_'): e for e in entities}
            self.assertEqual(by_suffix['downstream_power'].state, 2)
            self.assertEqual(by_suffix['downstream_snr'].state, 41)
            self.assertEqual(by_suffix['downstream_correcteds']._attr_state_class, 'total_increasing')
            self.api.aDev.return_value = {'hostTbl': []}
            await tick(None)
            self.assertEqual(by_suffix['hosts'].state, 0)
            self.assertEqual(by_suffix['missing_inactive_hosts'].state, 1)
            counts = [fn.call_count for fn in vars(self.api).values()]
            for e in entities:
                await e.async_update()
            self.assertEqual(counts, [fn.call_count for fn in vars(self.api).values()])
            self.api.system.side_effect = TimeoutError('offline')
            await tick(None)
            self.assertTrue(all(not e._attr_available for e in entities))
            self.api.system.side_effect = None
            await tick(None)
            self.assertTrue(all(e._attr_available for e in entities))
            self.assertEqual(len(entities), 19)

    async def test_healthy_setup_fetches_each_group_once(self):
        entry = SimpleNamespace(entry_id='test', options={}, data={})
        entities = []
        with patch.object(sensor, 'async_track_time_interval', Mock(return_value=Mock())):
            await sensor.async_setup_entry(self.hass, entry, lambda items, **kw: entities.extend(items))
        self.assertEqual(len(entities), 19)
        for fn in vars(self.api).values():
            self.assertEqual(fn.call_count, 1)
        self.assertTrue(all(e._attr_available for e in entities))

    async def test_resume_after_failed_unload(self):
        await self.poller.async_stop()
        self.assertFalse(await self.poller.async_refresh())
        self.poller.resume()
        self.assertTrue(await self.poller.async_refresh())
        self.assertEqual(len(self.poller.data), 5)

    async def test_invalid_response(self):
        for invalid in (None, {}, [], 'invalid'):
            self.api.system.return_value = invalid
            await self.poller.async_refresh()
            self.assertEqual(self.poller.data, {})
        self.api.dhcp.assert_not_called()


if __name__ == '__main__':
    unittest.main()
