"""Where the Power Meter window gets its readings: the meter itself, or a rig daemon.

The window only ever calls info(), read(), set(), zero() and close(). Both backends are
safe to call from the window's reader thread and its short-lived worker threads at once.
"""

from __future__ import annotations

import threading


class DirectMeter:
    """The instrument on this machine, opened with thorlabs_pm / oclab_rig.powermeter.
    `simulated=True` uses the simulator instead, to try the window with no meter attached."""

    def __init__(self, serial: str | None = None, simulated: bool = False):
        if simulated:
            from ..sim import SimPowerMeter   # relative, so the same file serves the rig and the package
            self._pm = SimPowerMeter()
        else:
            from ..powermeter import PowerMeter
            self._pm = PowerMeter(serial=serial)
        self._lock = threading.Lock()

    def info(self) -> dict:
        with self._lock:
            return self._pm.describe()

    def read(self, n: int = 1) -> dict:
        with self._lock:
            return self._pm.read(n=n)

    def set(self, **settings) -> dict:
        with self._lock:
            return self._pm.configure(**settings)

    def zero(self, on: bool = True) -> dict:
        with self._lock:
            return self._pm.zero(on)

    def close(self) -> None:
        with self._lock:
            self._pm.close()


class DaemonMeter:
    """A meter owned by an oclab-rig daemon, reached over its socket. Each call opens its own
    connection, which is how the daemon expects clients to behave."""

    def __init__(self, host: str = "127.0.0.1", port: int = 5710):
        self.host, self.port = host, port

    def _client(self, timeout_s: float = 10.0):
        from ..client import RigClient, RigError
        return RigClient(self.host, self.port, timeout_s=timeout_s), RigError

    def info(self) -> dict:
        client, RigError = self._client(5.0)
        with client as rig:
            info = rig.ping()
            pm = info["powermeter"]
            if pm is None:
                raise RigError(info["errors"].get("powermeter", "no power meter configured"))
            return pm

    def read(self, n: int = 1) -> dict:
        client, _ = self._client(10.0)
        with client as rig:
            return rig.call("power.read", n=n)[0]

    def set(self, **settings) -> dict:
        client, _ = self._client(10.0)
        with client as rig:
            return rig.power_set(**settings)

    def zero(self, on: bool = True) -> dict:
        client, _ = self._client(10.0)
        with client as rig:
            return rig.power_zero(on)

    def close(self) -> None:
        pass
