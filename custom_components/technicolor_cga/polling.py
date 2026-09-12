"""Shared router polling for all sensors in one integration.

How the modules work together:
  __init__.py  logs in to the API and stops the poller during unload.
  sensor.py    starts the first round and the timer (default: 300 seconds).
  polling.py   fetches groups serially and stores their shared snapshot.
  sensor.py    applies the snapshot; entity updates perform no HTTP requests.

One round:
  System -> DHCP -> Hosts -> DOCSIS -> WAN/LAN -> WiFi -> update sensors

Each group is called once, regardless of how many sensors consume it. A group
call may require additional HTTP requests for authentication. The API applies
the configured session takeover policy; the poller does not log in or log out.

Results are published only at the end of a round, including during setup.
Until then, self.data retains the previous snapshot. This class owns no timer
and does not immediately retry a failed round: the next refresh triggered by
the sensor module makes the next attempt.
"""

import asyncio
from datetime import datetime, timezone

import requests
import logging

_LOGGER = logging.getLogger(__name__)


class RouterPoller:
    """Collect one snapshot per round, with control running in the HA event loop.

    Only synchronous API calls run in the executor (worker thread). Flags and
    snapshots are modified in the event loop, not in those worker threads.
    """

    def __init__(self, hass, api):
        self.hass = hass
        # Keys match the groups below. A missing key means that the last published
        # round contained no valid data for that group.
        self.data = {}
        # The System sensor exposes these attributes even while unavailable.
        # last_success tracks complete fetch rounds, not logins or the subsequent
        # validation of every individual sensor field. Timestamps are UTC.
        self.diagnostics = {
            "poll_status": "not_started",
            "last_attempt": None,
            "last_success": None,
            "failed_group": None,
            "poll_error": None,
        }
        # _stopped: no new groups until resume() is called.
        # _busy: a round is running; additional starts are skipped, not queued.
        # _idle: unload may proceed once the current round has finished.
        self._stopped = False
        self._busy = False
        self._idle = asyncio.Event()
        self._idle.set()
        # Calls are deliberately serial because they share one router session.
        # DHCP feeds all DHCP sensors, Hosts feeds both device sensors, and so on.
        # API methods fetch fresh data; sharing happens through this snapshot.
        # WiFi is last so its failure cannot prevent earlier groups from loading.
        self._groups = (
            ("system", api.system),
            ("dhcp", api.dhcp),
            ("hosts", api.aDev),
            ("levels", api.levels),
            ("interfaces", api.interfaces),
            ("wifi", api.wifi),
        )

    async def async_refresh(self):
        """Fetch a round and publish its new, possibly incomplete snapshot.

        True: A snapshot was published and sensors should apply it. This does
              NOT mean that every group succeeded.
        False: Skipped or stopped because another round is running or shutdown
               was requested; do not publish new sensor data.
        CancelledError: Caller cancellation is propagated after the outstanding
                        executor call has finished.
        """
        if self._stopped or self._busy:
            return False
        # Check and set without an await: another event-loop task cannot start
        # an overlapping round between these two operations.
        self._busy = True
        self._idle.clear()
        self.diagnostics.update(
            poll_status="updating",
            last_attempt=datetime.now(timezone.utc).isoformat(),
            failed_group=None,
            poll_error=None,
        )
        # Collect locally so sensors cannot see a partially constructed snapshot.
        snapshot = {}
        try:
            for group, fetch in self._groups:
                if self._stopped:
                    return False
                # Only one group call runs at a time. HTTP timeouts are defined in the
                # API; a single group call may involve multiple HTTP steps.
                future = self.hass.async_add_executor_job(fetch)
                try:
                    # Cancelling a task cannot stop a requests thread already running.
                    # shield protects its future from cancellation. Drain the call before
                    # releasing the round guard so reload cannot use a new session while
                    # the previous request is still running.
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
                    # Partial WiFi response: one radio may fail while the other has data.
                    # Each sensor validates its own radio separately. Such a round does
                    # not count as fully successful.
                    if group == "wifi" and any(data.get(key) is None for key in ("1", "2")):
                        self.diagnostics.update(
                            poll_status="invalid_response", failed_group="wifi",
                            poll_error="One or more WiFi radios returned no valid data",
                        )
                except Exception as err:
                    # No retries per sensor and no further groups in this round. This
                    # prevents a login/connection failure from causing a chain of login
                    # attempts for all remaining sensors.
                    status, message = self._describe_error(err)
                    self.diagnostics.update(
                        poll_status=status, failed_group=group, poll_error=message,
                    )
                    _LOGGER.warning("Router refresh failed at %s; remaining groups skipped: %s", group, message)
                    break
            if self._stopped:
                return False
            # Replace the shared snapshot only now. For example, if DHCP fails,
            # only System is present; all remaining groups are missing and their
            # sensors become unavailable. Never present old values as fresh data.
            # sensor.py writes the resulting states to HA after this method returns.
            self.data = snapshot
            if len(snapshot) == len(self._groups) and self.diagnostics["poll_status"] == "updating":
                self.diagnostics.update(
                    poll_status="ok", last_success=datetime.now(timezone.utc).isoformat(),
                )
            return True
        finally:
            # Release async_stop() waiters even when the round fails or is stopped.
            self._busy = False
            self._idle.set()

    @staticmethod
    def _describe_error(err):
        """Classify errors for System attributes without exposing sensitive raw data.

        waiting_for_session comes from an explicit router response in the API;
        a missing challenge alone does not prove that a browser session is busy.
        Fixed messages keep cookies, tokens and response bodies out of attributes
        and logs.
        """
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
        """Called during unload after the timer has been unsubscribed.

        Set the stop flag before waiting. The current group call may finish,
        including a possible login retry. No further group will start and no
        new snapshot will be published. This neither immediately interrupts
        HTTP requests nor logs out of the router.
        """
        self._stopped = True
        await self._idle.wait()

    def resume(self):
        """Allow polling again only after an unsuccessful unload.

        __init__.py then restarts the timer. Ordinary HTTP failures do not need
        resume(): the existing timer continues running after those failures.
        """
        if self._busy:
            raise RuntimeError("Cannot resume a running poller")
        self._stopped = False
