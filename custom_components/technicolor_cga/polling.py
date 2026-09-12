"""One serial router fetch per data group, shared by all sensor entities."""

import asyncio
import logging

_LOGGER = logging.getLogger(__name__)


class RouterPoller:
    """Own snapshots and prevent concurrent rounds or requests after shutdown."""

    def __init__(self, hass, api):
        self.hass = hass
        self.data = {}
        self._stopped = False
        self._busy = False
        self._idle = asyncio.Event()
        self._idle.set()
        self._groups = (
            ("system", api.system),
            ("dhcp", api.dhcp),
            ("hosts", api.aDev),
            ("levels", api.levels),
            ("interfaces", api.interfaces),
        )

    async def async_refresh(self):
        """Fetch a fresh round; abort on failure rather than retry per sensor."""
        if self._stopped or self._busy:
            return False
        self._busy = True
        self._idle.clear()
        snapshot = {}
        try:
            for group, fetch in self._groups:
                if self._stopped:
                    return False
                future = self.hass.async_add_executor_job(fetch)
                try:
                    # Cancelling an asyncio waiter cannot stop a requests thread.
                    # Drain that request before releasing the serialization guard.
                    try:
                        data = await asyncio.shield(future)
                    except asyncio.CancelledError:
                        self._stopped = True
                        try:
                            await asyncio.shield(future)
                        except Exception:
                            pass
                        raise
                    if not isinstance(data, dict) or not data:
                        raise ValueError(f"Missing or invalid {group} data")
                    snapshot[group] = data
                except Exception as err:
                    _LOGGER.warning("Router refresh failed at %s; remaining groups skipped: %s", group, err)
                    break
            if self._stopped:
                return False
            # Missing groups become unavailable, never reuse an old round.
            self.data = snapshot
            return True
        finally:
            self._busy = False
            self._idle.set()

    async def async_stop(self):
        """Stop scheduling groups and wait for any in-flight request to finish."""
        self._stopped = True
        await self._idle.wait()

    def resume(self):
        """Resume only after an unsuccessful unload and a drained round."""
        if self._busy:
            raise RuntimeError("Cannot resume a running poller")
        self._stopped = False
