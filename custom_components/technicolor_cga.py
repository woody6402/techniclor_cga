import requests
import hashlib
import time

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
        request = self.session.get(endpoint)
        response = request.json()
        return response["data"]

    def challenge(self, password, salt):
        bpass = password.encode('utf-8')
        bsalt = salt.encode('utf-8')

        return hashlib.pbkdf2_hmac('sha256', bpass, bsalt, 1000).hex()[:32]

    def login(self):
        data = {
            "username": self.username,
            "password": "seeksalthash"
        }

        endpoint = self.endpoint("session", ["login"])
        request = self.session.post(endpoint, data=data)
        response = request.json()

        challenge = self.challenge(self.password, response['salt'])
        challenge = self.challenge(challenge, response['saltwebui'])

        data = {
            "username": "user",
            "password": challenge
        }

        endpoint = self.endpoint("session", ["login"])
        request = self.session.post(endpoint, data=data)
        response = request.json()

        if response['error'] == 'ok':
            self.session.headers.update({'X-CSRF-TOKEN': self.session.cookies['auth']})

            endpoint = self.endpoint("session", ["menu"])
            self.session.get(endpoint)

            self.logged = True

            return True

        raise RuntimeError("invalid credentials")

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
        options = [
            "exUSTbl",
            "exDSTbl",
            "USTbl",
            "DSTbl",
            "ErrTbl"
        ]

        endpoint = self.endpoint("modem", options)
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
        request = self.session.post(endpoint, data=data)
        response = request.json()

        return response['error'] == 'ok'

