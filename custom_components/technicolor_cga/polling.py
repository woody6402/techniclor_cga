"""One serial router fetch per data group, shared by all sensor entities."""

import asyncio
from datetime import datetime, timezone

import requests
from functools import partial
import logging

_LOGGER = logging.getLogger(__name__)


class RouterPoller:
    """Own snapshots and prevent concurrent rounds or requests after shutdown."""

    def __init__(self, hass, api):
        self.hass = hass
        self.data = {}
        self.diagnostics = {
            "poll_status": "not_started",
            "last_attempt": None,
            "last_success": None,
            "failed_group": None,
            "poll_error": None,
        }
        self._stopped = False
        self._busy = False
        self._idle = asyncio.Event()
        self._idle.set()
        self._groups = (
            ("system", api.system),
            ("dhcp", api.dhcp),
            ("hosts", api.aDev),
            ("levels", partial(api.levels, max_age=0)),
            ("interfaces", partial(api.interfaces, max_age=0)),
        )

    async def async_refresh(self):
        """Fetch a fresh round; abort on failure rather than retry per sensor."""
        if self._stopped or self._busy:
            return False
        self._busy = True
        self._idle.clear()
        self.diagnostics.update(
            poll_status="updating",
            last_attempt=datetime.now(timezone.utc).isoformat(),
            failed_group=None,
            poll_error=None,
        )
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
                    status, message = self._describe_error(err)
                    self.diagnostics.update(
                        poll_status=status, failed_group=group, poll_error=message,
                    )
                    _LOGGER.warning("Router refresh failed at %s; remaining groups skipped: %s", group, message)
                    break
            if self._stopped:
                return False
            # Missing groups become unavailable, never reuse an old round.
            self.data = snapshot
            if len(snapshot) == len(self._groups):
                self.diagnostics.update(
                    poll_status="ok", last_success=datetime.now(timezone.utc).isoformat(),
                )
            return True
        finally:
            self._busy = False
            self._idle.set()

    @staticmethod
    def _describe_error(err):
        # Fixed descriptions keep cookies, tokens and response bodies out of
        # persistent HA attributes and the log.
        status = getattr(err, "poll_status", None)
        if status == "waiting_for_session":
            return status, "Router reports an occupied session; retrying later"
        if status == "login_failed":
            return status, "Router did not grant login; retrying later"
        if isinstance(err, (requests.Timeout, TimeoutError)):
            return "timeout", "Router request timed out"
        if isinstance(err, requests.ConnectionError):
            return "connection_error", "Could not connect to router"
        if isinstance(err, (ValueError, KeyError, TypeError)):
            return "invalid_response", "Router returned missing or invalid data"
        return "error", "Router refresh failed"

    async def async_stop(self):
        """Stop scheduling groups and wait for any in-flight request to finish."""
        self._stopped = True
        await self._idle.wait()

    def resume(self):
        """Resume only after an unsuccessful unload and a drained round."""
        if self._busy:
            raise RuntimeError("Cannot resume a running poller")
        self._stopped = False
