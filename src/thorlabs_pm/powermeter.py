"""Thorlabs PM16 / PM160 / PM100-family power meters over the Linux usbtmc driver.

Thorlabs' Optical Power Monitor app and TLPM DLLs are Windows-only, but the meters are ordinary
USBTMC instruments speaking SCPI, so the kernel driver is all that is needed: no VISA, no NI.
"""

from __future__ import annotations

import fcntl
import glob
import os
import struct

import numpy as np

THORLABS_VENDOR = "1313"
USBTMC_IOCTL_SET_TIMEOUT = 0x40045B0A  # _IOW('[', 10, __u32)
USBTMC_IOCTL_CLEAR = 0x00005B02        # _IO('[', 2): USBTMC INITIATE_CLEAR, unsticks a stalled bulk pipe


def find_usbtmc(serial: str | None = None, vendor: str = THORLABS_VENDOR) -> list[dict]:
    """usbtmc devices from `vendor`: [{"path", "serial", "product"}], optionally filtered by serial."""
    found = []
    for cls in sorted(glob.glob("/sys/class/usbmisc/usbtmc*")):
        usb_device = os.path.dirname(os.path.realpath(os.path.join(cls, "device")))

        def attr(name: str) -> str:
            try:
                with open(os.path.join(usb_device, name)) as f:
                    return f.read().strip()
            except OSError:
                return ""

        if attr("idVendor") == vendor and (serial is None or attr("serial") == str(serial)):
            found.append({"path": "/dev/" + os.path.basename(cls), "serial": attr("serial"), "product": attr("product")})
    return found


class PowerMeter:
    def __init__(self, serial: str | int | None = None, wavelength_nm: float | None = None, timeout_ms: int = 3000):
        matches = find_usbtmc(None if serial is None else str(serial))
        if not matches:
            raise LookupError(f"no Thorlabs usbtmc device{f' with serial {serial}' if serial else ''} "
                              f"(connected: {find_usbtmc() or 'none'})")
        self.path, self.serial = matches[0]["path"], matches[0]["serial"]
        self._fd = os.open(self.path, os.O_RDWR)
        fcntl.ioctl(self._fd, USBTMC_IOCTL_SET_TIMEOUT, struct.pack("I", timeout_ms))
        self.idn = self.query("*IDN?")
        # "name,serial,calibration date,type,subtype,flags" for the sensor head (PM16 = head + meter in one)
        sensor = self.query("SYST:SENS:IDN?").split(",")
        self.sensor = {"name": sensor[0], "serial": sensor[1] if len(sensor) > 1 else "",
                       "calibration_date": sensor[2] if len(sensor) > 2 else ""}
        self.wavelength_range_nm = [float(self.query("SENS:CORR:WAV? MIN")), float(self.query("SENS:CORR:WAV? MAX"))]
        self.wavelength_nm = None
        self._static: dict | None = None
        self.configure(wavelength_nm=wavelength_nm)

    def write(self, command: str) -> None:
        os.write(self._fd, (command + "\n").encode())

    def query(self, command: str) -> str:
        try:
            self.write(command)
            return os.read(self._fd, 4096).decode(errors="replace").strip()
        except TimeoutError:
            # An unsupported command (or a stray probe) leaves the instrument mid-transfer; a USBTMC
            # clear resets the pipes and the next query works. Retry exactly once.
            fcntl.ioctl(self._fd, USBTMC_IOCTL_CLEAR)
            self.write(command)
            return os.read(self._fd, 4096).decode(errors="replace").strip()

    def _write_checked(self, command: str) -> None:
        """Write, then read the instrument's error queue: an unsupported setting fails loudly instead of silently."""
        self.write(command)
        error = self.query("SYST:ERR?")
        if not error.startswith("0"):
            raise ValueError(f"the meter rejected {command!r}: {error}")

    def zero(self, on: bool = True) -> dict:
        """Store the present reading as the dark level (the meter subtracts it), or clear it."""
        self._write_checked("SENS:CORR:COLL:ZERO:INIT" if on else "SENS:CORR:COLL:ZERO:ABOR")
        self._static = None
        return self.describe()

    def configure(self, wavelength_nm: float | None = None, unit: str | None = None, relative: bool | None = None,
                  reference_w: float | None = None, range_w: float | None = None, auto_range: bool | None = None) -> dict:
        """Wavelength in nm, display unit ("W" or "DBM"), relative mode against `reference_w` (None keeps the
        present reading as the reference), and the measurement range: `auto_range` or a fixed `range_w`."""
        if unit is not None:
            if unit.upper() not in ("W", "DBM"):
                raise ValueError("unit must be 'W' or 'DBM'")
            self._write_checked(f"SENS:POW:UNIT {unit.upper()}")
            self._static = None
        if reference_w is not None:
            self._write_checked(f"SENS:POW:REF {float(reference_w)}")
            self._static = None
        if relative is not None:
            self._write_checked(f"SENS:POW:REF:STAT {1 if relative else 0}")
            self._static = None
        if auto_range is not None:
            self._write_checked(f"SENS:POW:RANG:AUTO {1 if auto_range else 0}")
            self._static = None
        if range_w is not None:
            self._write_checked("SENS:POW:RANG:AUTO 0")
            self._write_checked(f"SENS:POW:RANG {float(range_w)}")
            self._static = None
        if wavelength_nm is not None:
            lo, hi = self.wavelength_range_nm
            if not lo <= float(wavelength_nm) <= hi:
                raise ValueError(f"{wavelength_nm} nm is outside this head's range {lo:.0f}-{hi:.0f} nm "
                                 f"({self.idn.split(',')[1]})")
            self.write(f"SENS:CORR:WAV {float(wavelength_nm)}")
        self.wavelength_nm = float(self.query("SENS:CORR:WAV?"))
        return self.describe()

    def read(self, n: int = 1) -> dict:
        watts = np.array([float(self.query("MEAS:POW?")) for _ in range(max(1, int(n)))])
        mean = float(watts.mean())
        return {"watts": mean, "std_watts": float(watts.std()), "n": int(watts.size),
                "wavelength_nm": self.wavelength_nm,
                "dbm": float(10 * np.log10(mean / 1e-3)) if mean > 0 else None}   # computed here: the meter keeps its own unit

    def describe(self) -> dict:
        """Everything the PM16 will tell us about how it is set up. Cached: each of these is a USB round trip,
        and clients ask often. Any setter clears the cache."""
        if getattr(self, "_static", None) is None:
            self._static = {
                "range_w": self._float_or_none("SENS:POW:RANG?"),
                "auto_range": self.query("SENS:POW:RANG:AUTO?") == "1",
                "unit": self.query("SENS:POW:UNIT?"),
                "relative": self.query("SENS:POW:REF:STAT?") == "1",
                "reference_w": self._float_or_none("SENS:POW:REF?"),
                "dark_level_w": self._float_or_none("SENS:CORR:COLL:ZERO:MAGN?"),
                "zeroed": self.query("SENS:CORR:COLL:ZERO:STAT?") == "1",
                "responsivity_a_per_w": self._float_or_none("SENS:CORR:POW?"),
            }
        return {"idn": self.idn, "path": self.path, "serial": self.serial, "wavelength_nm": self.wavelength_nm,
                "wavelength_range_nm": self.wavelength_range_nm, "sensor": self.sensor,
                "amps": self._float_or_none("MEAS:CURR?"), **self._static}

    def _float_or_none(self, command: str):
        try:
            return float(self.query(command))
        except (OSError, ValueError):
            return None

    def __enter__(self) -> "PowerMeter":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        os.close(self._fd)
