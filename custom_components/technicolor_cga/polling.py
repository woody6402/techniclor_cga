"""Gemeinsame Router-Abfragen für alle Sensoren einer Integration.

Zusammenspiel der Dateien:
  __init__.py  meldet die API an und stoppt den Poller beim Entladen.
  sensor.py    startet die erste Runde und den Timer (Standard: 300 Sekunden).
  polling.py   holt die Daten seriell und hält den gemeinsamen Datensatz bereit.
  sensor.py    verteilt danach die Daten: Entity-Updates machen selbst kein HTTP.

Eine Runde:
  System -> DHCP -> Hosts -> DOCSIS -> WAN/LAN -> WLAN -> Sensoren aktualisieren

Jede Datengruppe wird einmal aufgerufen, unabhängig von der Anzahl ihrer
Sensoren. Ein Gruppenaufruf kann intern zusätzliche HTTP-Anfragen zur Anmeldung
benötigen. Die API entscheidet anhand der Login-Option, ob eine belegte Sitzung
übernommen werden darf; der Poller selbst meldet niemanden an oder ab.

Die Ergebnisse werden erst am Ende der Runde veröffentlicht, auch beim Setup.
Bis dahin bleibt self.data der vorherige Datensatz. Es gibt keinen eigenen
Timer in dieser Klasse und keine sofortige Wiederholung nach einem Fehler:
Erst der nächste vom Sensor-Modul gestartete Durchlauf versucht es erneut.
"""

import asyncio
from datetime import datetime, timezone

import requests
from functools import partial
import logging

_LOGGER = logging.getLogger(__name__)


class RouterPoller:
    """Sammelt einen Datensatz pro Runde; Steuerung erfolgt im HA-Event-Loop.

    Nur die synchronen API-Aufrufe laufen im Executor (Hintergrundthread).
    Flags und Datensätze werden im Event-Loop geändert, nicht in diesen Threads.
    """

    def __init__(self, hass, api):
        self.hass = hass
        # Schlüssel entsprechen den Gruppen unten. Fehlender Schlüssel bedeutet:
        # In der letzten veröffentlichten Runde gab es dafür keine gültigen Daten.
        self.data = {}
        # Der System-Sensor zeigt diese Werte auch bei unavailable als Attribute.
        # last_success zählt vollständige Abrufrunden, nicht erfolgreiche Logins
        # oder die spätere Auswertung jedes einzelnen Sensorfeldes. Zeiten: UTC.
        self.diagnostics = {
            "poll_status": "not_started",
            "last_attempt": None,
            "last_success": None,
            "failed_group": None,
            "poll_error": None,
        }
        # _stopped: dauerhaft keine neuen Gruppen, bis resume() aufgerufen wird.
        # _busy: eine Runde läuft; weitere Starts werden übersprungen, nicht queued.
        # _idle: Entladen darf weitergehen, sobald die laufende Runde beendet ist.
        self._stopped = False
        self._busy = False
        self._idle = asyncio.Event()
        self._idle.set()
        # Reihenfolge ist bewusst seriell: dieselbe Router-Session wird geteilt.
        # DHCP versorgt alle DHCP-Sensoren, Hosts beide Geräte-Sensoren usw.
        # max_age=0 umgeht die kurzen API-Caches: jede Runde holt frische Daten.
        # WLAN steht zuletzt, damit sein Ausfall frühere Gruppen nicht verhindert.
        self._groups = (
            ("system", api.system),
            ("dhcp", api.dhcp),
            ("hosts", api.aDev),
            ("levels", partial(api.levels, max_age=0)),
            ("interfaces", partial(api.interfaces, max_age=0)),
            ("wifi", api.wifi),
        )

    async def async_refresh(self):
        """Eine Runde abholen und den neuen (ggf. unvollständigen) Satz publizieren.

        True: Ein Datensatz wurde veröffentlicht; Sensoren sollen ihn anwenden.
              Das bedeutet NICHT, dass alle Gruppen erfolgreich waren.
        False: Wegen laufender Runde oder Stop übersprungen/abgebrochen; keine
               neuen Sensordaten veröffentlichen.
        CancelledError: Abbruch durch den Aufrufer wird nach dem Abwarten des
                        laufenden Executor-Aufrufs weitergereicht.
        """
        if self._stopped or self._busy:
            return False
        # Prüfung und Setzen passieren ohne await: ein zweiter Event-Loop-Task
        # kann nicht dazwischen eine weitere Runde starten.
        self._busy = True
        self._idle.clear()
        self.diagnostics.update(
            poll_status="updating",
            last_attempt=datetime.now(timezone.utc).isoformat(),
            failed_group=None,
            poll_error=None,
        )
        # Lokal sammeln, damit Sensoren keinen halb aufgebauten Satz sehen.
        snapshot = {}
        try:
            for group, fetch in self._groups:
                if self._stopped:
                    return False
                # Genau ein Gruppenaufruf gleichzeitig. Die HTTP-Timeouts liegen
                # in der API; ein Gruppenaufruf kann mehrere HTTP-Schritte haben.
                future = self.hass.async_add_executor_job(fetch)
                try:
                    # Task-Abbruch beendet keinen bereits laufenden requests-Thread.
                    # shield verhindert das Canceln seines Future. Erst abwarten,
                    # dann die Rundensperre lösen, damit ein Reload nicht parallel
                    # zur alten Anfrage eine neue Session benutzt.
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
                    # Sonderfall: Ein Radio darf fehlen, während das andere noch
                    # Daten liefert. Beide Sensoren prüfen ihren Teil separat.
                    # Die Runde gilt dabei nicht als vollständig erfolgreich.
                    if group == "wifi" and any(data.get(key) is None for key in ("1", "2")):
                        self.diagnostics.update(
                            poll_status="invalid_response", failed_group="wifi",
                            poll_error="One or more WiFi radios returned no valid data",
                        )
                except Exception as err:
                    # Kein Wiederholen je Sensor und keine weiteren Gruppen in
                    # dieser Runde. So erzeugt ein Login-/Verbindungsfehler keine
                    # Kette weiterer Anmeldeversuche für alle Sensoren.
                    status, message = self._describe_error(err)
                    self.diagnostics.update(
                        poll_status=status, failed_group=group, poll_error=message,
                    )
                    _LOGGER.warning("Router refresh failed at %s; remaining groups skipped: %s", group, message)
                    break
            if self._stopped:
                return False
            # Erst jetzt atomar den gemeinsamen Satz ersetzen. Beispiel: DHCP
            # scheitert -> nur System ist enthalten; alle übrigen Gruppen fehlen
            # und ihre Sensoren werden unavailable. Alte Werte werden nicht als
            # frische Daten übernommen. sensor.py schreibt danach die HA-Zustände.
            self.data = snapshot
            if len(snapshot) == len(self._groups) and self.diagnostics["poll_status"] == "updating":
                self.diagnostics.update(
                    poll_status="ok", last_success=datetime.now(timezone.utc).isoformat(),
                )
            return True
        finally:
            # Auch bei Fehler oder Stop den Wartenden in async_stop() freigeben.
            self._busy = False
            self._idle.set()

    @staticmethod
    def _describe_error(err):
        """Fehler für die System-Attribute klassifizieren, ohne sensible Rohdaten.

        waiting_for_session kommt von einer expliziten Routermeldung in der API;
        eine bloß fehlende Challenge beweist keine belegte Browser-Sitzung.
        Feste Texte verhindern Cookies/Token/Antwortinhalte in Attributen und Log.
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
        """Nach Timer-Abmeldung beim Entladen aufgerufen.

        Das Stop-Flag wird vor dem Warten gesetzt. Die gerade laufende Gruppe
        darf noch fertig werden (inklusive eines möglichen Login-Retry), danach
        wird keine weitere Gruppe gestartet und kein neuer Satz veröffentlicht.
        Dies ist kein sofortiger HTTP-Abbruch und kein Router-Logout.
        """
        self._stopped = True
        await self._idle.wait()

    def resume(self):
        """Nur nach fehlgeschlagenem Entladen wieder freigeben.

        __init__.py startet anschließend den Timer erneut. Reguläre HTTP-Fehler
        brauchen kein resume(): nach ihnen läuft der vorhandene Timer weiter.
        """
        if self._busy:
            raise RuntimeError("Cannot resume a running poller")
        self._stopped = False
