import requests
import hashlib
import time

# Connect and read inactivity timeouts in seconds (not a total request deadline).
REQUEST_TIMEOUT = (5, 15)

class TechnicolorCGA:
    def __init__(self, username, password, router="192.168.0.1"):
        self.server = f"http://{router}"
        self.username = username
        self.password = password

        self.logged = False

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

    def _request_salt(self, logout):
        data = {
            "username": self.username,
            "password": "seeksalthash",
            "logout": "true" if logout else "false",
        }
        endpoint = self.endpoint("session", ["login"])
        return self.session.post(endpoint, data=data, timeout=REQUEST_TIMEOUT).json()

    def login(self):
        # Seed a session cookie (PHPSESSID) first: the modem's own web UI does
        # a GET on session/menu before logging in. Without it the salt request
        # comes back as MSG_LOGIN_150 ("already logged in") with no salt.
        self.session.get(self.endpoint("session", ["menu"]), timeout=REQUEST_TIMEOUT)

        response = self._request_salt(logout=False)
        if "salt" not in response:
            # A previous session is still held (single-session device). Ask the
            # modem to drop it and hand us the salt, like the web UI does when
            # it hits MSG_LOGIN_150.
            response = self._request_salt(logout=True)

        challenge = self.challenge(self.password, response["salt"])
        challenge = self.challenge(challenge, response["saltwebui"])

        data = {
            "username": self.username,
            "password": challenge,
        }

        endpoint = self.endpoint("session", ["login"])
        response = self.session.post(endpoint, data=data, timeout=REQUEST_TIMEOUT).json()

        if response.get("error") == "ok":
            self.session.headers.update({'X-CSRF-TOKEN': self.session.cookies['auth']})

            endpoint = self.endpoint("session", ["menu"])
            self.session.get(endpoint, timeout=REQUEST_TIMEOUT)

            self.logged = True

            return True

        raise RuntimeError(f"login failed: {response.get('message', response)}")

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

    def levels(self):
        """Fetch fresh DOCSIS tables; the poller shares them across sensors."""
        options = [
            "exUSTbl",
            "exDSTbl",
            "USTbl",
            "DSTbl",
            "ErrTbl"
        ]

        endpoint = self.endpoint("modem", options)
        return self.call(endpoint)

    def interfaces(self):
        """Fetch fresh interface statistics once per central polling round."""
        endpoint = self.endpoint("dig_interface", [])
        return self.call(endpoint)

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

