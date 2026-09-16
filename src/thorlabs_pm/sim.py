"""A simulated meter with the same interface as thorlabs_pm.PowerMeter."""

from __future__ import annotations

import threading
import time

import numpy as np


class SimPowerMeter:
    def __init__(self, serial="SIM0002", wavelength_nm=None, **_):
        self.serial, self.path = str(serial), "sim"
        self.idn = f"Thorlabs,SIM-PM,{self.serial},1.0"
        self.wavelength_range_nm = [400.0, 1100.0]
        self.wavelength_nm = 532.0
        self.unit, self.relative, self.reference_w = "W", False, 0.0
        self.range_w, self.auto_range, self.dark_level_w, self.zeroed = 1e-2, True, 0.0, False
        self._rng = np.random.default_rng(1)
        self.configure(wavelength_nm=wavelength_nm)

    def configure(self, wavelength_nm=None, unit=None, relative=None, reference_w=None,
                  range_w=None, auto_range=None) -> dict:
        if wavelength_nm is not None:
            lo, hi = self.wavelength_range_nm
            if not lo <= float(wavelength_nm) <= hi:
                raise ValueError(f"{wavelength_nm} nm is outside this head's range {lo:.0f}-{hi:.0f} nm (SIM-PM)")
            self.wavelength_nm = float(wavelength_nm)
        if unit is not None:
            if str(unit).upper() not in ("W", "DBM"):
                raise ValueError("unit must be 'W' or 'DBM'")
            self.unit = str(unit).upper()
        if reference_w is not None:
            self.reference_w = float(reference_w)
        if relative is not None:
            self.relative = bool(relative)
        if auto_range is not None:
            self.auto_range = bool(auto_range)
        if range_w is not None:
            self.range_w, self.auto_range = float(range_w), False
        return self.describe()

    def zero(self, on: bool = True) -> dict:
        self.dark_level_w = float(self.read(4)["watts"]) if on else 0.0
        self.zeroed = bool(on)
        return self.describe()

    def read(self, n: int = 1) -> dict:
        w = 1e-3 + self._rng.normal(0, 2e-6, max(1, int(n))) - self.dark_level_w
        time.sleep(0.02 * max(1, int(n)))
        mean = float(w.mean()) - (self.reference_w if self.relative else 0.0)
        return {"watts": mean, "std_watts": float(w.std()), "n": int(w.size), "wavelength_nm": self.wavelength_nm,
                "dbm": float(10 * np.log10(mean / 1e-3)) if mean > 0 else None}

    def describe(self) -> dict:
        return {"idn": self.idn, "path": self.path, "serial": self.serial, "wavelength_nm": self.wavelength_nm,
                "wavelength_range_nm": self.wavelength_range_nm,
                "sensor": {"name": "SIM-PM", "serial": self.serial, "calibration_date": "01-JAN-2026"},
                "range_w": self.range_w, "auto_range": self.auto_range, "unit": self.unit,
                "relative": self.relative, "reference_w": self.reference_w, "dark_level_w": self.dark_level_w,
                "zeroed": self.zeroed, "responsivity_a_per_w": 3.0e-3, "amps": 3.0e-6}

    def close(self) -> None:
        pass
