import requests
import hashlib
import time

# Connect and read inactivity timeouts in seconds (not a total request deadline).
REQUEST_TIMEOUT = (5, 15)

class RouterLoginError(RuntimeError):
    poll_status = "login_failed"


class RouterSessionBusy(RouterLoginError):
    poll_status = "waiting_for_session"


class TechnicolorCGA:
    def __init__(self, username, password, router="192.168.0.1"):
        self.server = f"http://{router}"
        self.username = username
        self.password = password

        self.logged = False

        # short-lived cache for the DOCSIS levels() tables so that several
        # sensors sharing one update cycle only trigger a single HTTP request
        # (the modem only allows one session at a time).
        self._levels_cache = None
        self._levels_ts = 0.0
        self._iface_cache = None
        self._iface_ts = 0.0

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/105.0.0.0 Safari/537.36"})
        self.session.headers.update({"X-Requested-With": "XMLHttpRequest"})

    def endpoint(self, target, options):
        opts = ",".join(options)
        now = int(time.time())

        if len(options) == 0:
            return f"{self.server}/api/v1/{target}?_={now}"

        return f"{self.server}/api/v1/{target}/{opts}?_={now}"

    def call(self, endpoint):
        response = self.session.get(endpoint, timeout=REQUEST_TIMEOUT).json()

        # The modem drops idle sessions (and only allows one at a time), after
        # which requests come back as {"error": "error", "message":
        # "Unauthorized!"} with no "data" key. Re-authenticate once and retry
        # so the integration recovers on its own instead of going stale until
        # Home Assistant is restarted.
        if "data" not in response:
            self.login()
            response = self.session.get(endpoint, timeout=REQUEST_TIMEOUT).json()

        return response["data"]

    def challenge(self, password, salt):
        bpass = password.encode('utf-8')
        bsalt = salt.encode('utf-8')

        return hashlib.pbkdf2_hmac('sha256', bpass, bsalt, 1000).hex()[:32]

    def _request_salt(self):
        data = {
            "username": self.username,
            "password": "seeksalthash",
            "logout": "false",
        }
        endpoint = self.endpoint("session", ["login"])
        return self.session.post(endpoint, data=data, timeout=REQUEST_TIMEOUT).json()

    def login(self):
        self.logged = False
        # Seed a session cookie (PHPSESSID) first: the modem's own web UI does
        # a GET on session/menu before logging in. Without it the salt request
        # comes back as MSG_LOGIN_150 ("already logged in") with no salt.
        self.session.get(self.endpoint("session", ["menu"]), timeout=REQUEST_TIMEOUT)

        response = self._request_salt()
        if not response.get("salt") or not response.get("saltwebui"):
            # Never evict a browser (or another client) on this single-session
            # router. Setup/polling will retry later when access is available.
            error_type = (
                RouterSessionBusy
                if "MSG_LOGIN_150" in (response.get("message"), response.get("error"), response.get("code"))
                else RouterLoginError
            )
            raise error_type(
                "Router did not grant a login challenge; session may be occupied. "
                "Existing session left untouched; will retry later."
            )

        challenge = self.challenge(self.password, response["salt"])
        challenge = self.challenge(challenge, response["saltwebui"])

        data = {
            "username": self.username,
            "password": challenge,
            "logout": "false",
        }

        endpoint = self.endpoint("session", ["login"])
        response = self.session.post(endpoint, data=data, timeout=REQUEST_TIMEOUT).json()

        if response.get("error") == "ok":
            self.session.headers.update({'X-CSRF-TOKEN': self.session.cookies['auth']})

            endpoint = self.endpoint("session", ["menu"])
            self.session.get(endpoint, timeout=REQUEST_TIMEOUT)

            self.logged = True

            return True

        raise RouterLoginError("Router rejected the login")

    def system(self):
        options = [
            "HardwareVersion",
            "FirmwareName",
            "CMMACAddress",
            "MACAddressRT",
            "UpTime",
            "LocalTime",
            "LanMode",
            "ModelName",
            "CMStatus",
            "ModelName",
            "Manufacturer",
            "SerialNumber",
            "SoftwareVersion",
            "BootloaderVersion",
            "CoreVersion",
            "FirmwareBuildTime",
            "ProcessorSpeed",
            "CMMACAddress",
            "Hardware",
            "MemTotal",
            "MemFree"
        ]

        endpoint = self.endpoint("system", options)
        return self.call(endpoint)

    def levels(self, max_age=10):
        # Reuse a recent result so the several DOCSIS sensors that run in the
        # same update pass don't each hit the modem separately.
        if self._levels_cache is not None and (time.time() - self._levels_ts) < max_age:
            return self._levels_cache

        options = [
            "exUSTbl",
            "exDSTbl",
            "USTbl",
            "DSTbl",
            "ErrTbl"
        ]

        endpoint = self.endpoint("modem", options)
        data = self.call(endpoint)
        self._levels_cache = data
        self._levels_ts = time.time()
        return data

    def interfaces(self, max_age=10):
        # WAN/LAN/WiFi interface statistics (dig_interface). Cached like
        # levels() so the WAN/LAN sensors share one request per update pass.
        if self._iface_cache is not None and (time.time() - self._iface_ts) < max_age:
            return self._iface_cache

        endpoint = self.endpoint("dig_interface", [])
        data = self.call(endpoint)
        self._iface_cache = data
        self._iface_ts = time.time()
        return data

    def dhcp(self):
        options = [
            "IPAddressRT",
            "SubnetMaskRT",
            "IPAddressGW",
            "DNSTblRT",
            "PoolEnable",
            "WanAddressMode"
        ]

        endpoint = self.endpoint("dhcp/v4/1", options)
        return self.call(endpoint)

    def aDev(self):
        options = [ "hostTbl", "LanMode" , "MixedMode" , "LanPortMode" ]

        endpoint = self.endpoint("host", options)
        return self.call(endpoint)

    def reboot(self):
        endpoint = self.endpoint("reset", [])

        data = {"reboot": "Router,Wifi,VoIP,Dect,MoCA"}
        request = self.session.post(endpoint, data=data, timeout=REQUEST_TIMEOUT)
        response = request.json()

        return response['error'] == 'ok'

