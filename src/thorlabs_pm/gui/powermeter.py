"""Power Meter: a Linux stand-in for Thorlabs' Optical Power Monitor.

Live reading with SI units or dBm, wavelength, averaging, the meter's own dark-level zero and relative mode,
manual or automatic range, min/max/mean since reset, a scrolling chart and CSV logging. Readings come from a
meter backend (gui/meters.py): the instrument directly, or an oclab-rig daemon that owns it.
"""

from __future__ import annotations

import csv
import json
import threading
import time
from collections import deque
from pathlib import Path

from .meters import DaemonMeter, DirectMeter
from . import format_watts, require_gtk
from . import plot, ui

Adw, Gdk, GLib, Gtk = require_gtk()

WINDOWS_S = (30, 120, 600, 3600)
SETTINGS_FILE = Path(GLib.get_user_config_dir()) / "oclab-rig" / "powermeter.json"


class PowerMeterWindow(Adw.ApplicationWindow):
    def __init__(self, app, meter):
        super().__init__(application=app, title="Power Meter")
        ui.remember_size(self, "powermeter", (940, 620))
        ui.apply_instrument_style(self)
        self.meter = meter
        self.connected = False
        self.zeroed = False
        self._syncing = False          # true while the toggles are being set from the meter's own state
        self.history: deque[tuple[float, float]] = deque()
        self.history_s = 120
        self.stats = self._fresh_stats()
        self.log_file = self.log_writer = None
        self._prefs = self._load_prefs()
        self._build()
        self.connect("close-request", lambda *_: setattr(self, "_stop", True) and False)
        self._stop = False
        threading.Thread(target=self._reader, daemon=True).start()

    # --- UI -------------------------------------------------------------------------------------

    def _build(self):
        header = Adw.HeaderBar()
        self.device_chip, self.device_dot, self.device_name = ui.chip("connecting…", "idle")
        header.set_title_widget(self.device_chip)
        self.live = Gtk.Label(label="LIVE")
        self.live.add_css_class("live-badge")
        self.live.set_visible(False)
        header.pack_start(self.live)
        self.log_button = Gtk.ToggleButton(icon_name="document-save-symbolic", tooltip_text="Log readings to a CSV file")
        self.log_button.connect("toggled", self._on_log_toggled)
        header.pack_end(self.log_button)
        copy = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Copy the current reading (watts) to the clipboard")
        copy.connect("clicked", lambda *_: self.history and self.get_clipboard().set(f"{self.history[-1][1]:.6e}"))
        header.pack_end(copy)

        # ---- settings column, the way every instrument tool arranges its device controls
        self.wavelength = Gtk.SpinButton.new_with_range(300, 2000, 1)
        self.wavelength.connect("value-changed", self._on_wavelength)
        self.averaging = Gtk.SpinButton.new_with_range(1, 100, 1)
        self.averaging.set_value(self._prefs.get("averaging", 1))
        self.averaging.connect("value-changed", lambda s: self._save_prefs(averaging=int(s.get_value())))
        self.autorange = Gtk.ToggleButton(label="Auto range", active=True, tooltip_text="Let the meter choose its measurement range")
        self.autorange.connect("toggled", lambda b: self._syncing or self._apply_async(
            lambda meter, on=b.get_active(): meter.set(auto_range=on)))
        self.relative = Gtk.ToggleButton(label="Relative", tooltip_text="The meter's own relative mode: readings against a stored reference")
        self.relative.connect("toggled", lambda b: self._syncing or self._apply_async(
            lambda meter, on=b.get_active(): meter.set(relative=on)))
        set_ref = Gtk.Button(label="Set reference", tooltip_text="Make the present reading the reference for relative mode")
        set_ref.connect("clicked", lambda *_: self._apply_async(self._set_reference))
        zero = Gtk.Button(label="Zero", tooltip_text="Store what the meter reads now as its dark level (the meter subtracts it)")
        zero.connect("clicked", lambda *_: self._apply_async(self._zero_on))
        unzero = Gtk.Button(label="Clear")
        unzero.connect("clicked", lambda *_: self._apply_async(self._zero_off))
        self.dbm = Gtk.ToggleButton(label="dBm", active=bool(self._prefs.get("dbm", False)),
                                    tooltip_text="Show the reading in dBm; the chart, statistics and CSV stay in watts")
        self.dbm.connect("toggled", lambda b: self._save_prefs(dbm=b.get_active()))
        self.window_drop = Gtk.DropDown.new_from_strings([f"{w // 60} min" if w >= 60 else f"{w} s" for w in WINDOWS_S])
        self.window_drop.set_selected(WINDOWS_S.index(120))
        self.window_drop.set_tooltip_text("Chart time window")
        self.window_drop.connect("notify::selected", lambda d, _p: (setattr(self, "history_s", WINDOWS_S[d.get_selected()]),
                                                                    self.chart.queue_draw()))
        reset = Gtk.Button(label="Reset min/max")
        reset.connect("clicked", lambda *_: setattr(self, "stats", self._fresh_stats()))

        settings = ui.panel(width_request=232, margin_end=0)
        settings.append(ui.panel_title("Measurement"))
        settings.append(ui.field("Wavelength (nm)", self.wavelength))
        settings.append(ui.field("Averaging (reads)", self.averaging))
        settings.append(self.autorange)
        settings.append(Gtk.Separator())
        settings.append(ui.panel_title("Reference"))
        settings.append(self.relative)
        settings.append(set_ref)
        settings.append(Gtk.Separator())
        settings.append(ui.panel_title("Dark level"))
        settings.append(ui.group(zero, unzero))
        settings.append(Gtk.Separator())
        settings.append(ui.panel_title("Display"))
        settings.append(self.dbm)
        settings.append(ui.field("Chart window", self.window_drop))
        settings.append(reset)
        self.meter_label = Gtk.Label(xalign=0, wrap=True, valign=Gtk.Align.END, vexpand=True)
        self.meter_label.add_css_class("hint")
        settings.append(self.meter_label)

        # ---- the reading: quantity, then the number, then the unit beside it
        self.quantity = Gtk.Label(label="Power", xalign=0)
        self.quantity.add_css_class("readout-quantity")
        self.sub = Gtk.Label(xalign=0)
        self.sub.add_css_class("hint")
        self.value = Gtk.Label(xalign=1, hexpand=True)
        self.value.add_css_class("readout-value")
        self.value.set_markup('<span size="42000">—</span>')
        self.unit = Gtk.Label(label="W", valign=Gtk.Align.END, margin_bottom=8)
        self.unit.add_css_class("readout-unit")
        number = Gtk.Box(spacing=10, halign=Gtk.Align.FILL, margin_top=4, margin_bottom=2)
        number.append(self.value)
        number.append(self.unit)
        self.bar = Gtk.LevelBar(min_value=0, max_value=1)

        reading = ui.panel(margin_bottom=0)
        reading.append(self.quantity)
        reading.append(self.sub)
        reading.append(number)
        reading.append(self.bar)

        self.tiles = {}
        tiles_row = Gtk.Box(spacing=8, margin_start=10, margin_end=10, margin_top=8, homogeneous=True)
        for name in ("Maximum", "Minimum", "Mean", "Std dev", "Samples"):
            box, value, unit = ui.tile(name)
            self.tiles[name] = (value, unit)
            tiles_row.append(box)

        self.chart = Gtk.DrawingArea(vexpand=True, height_request=170, margin_start=10, margin_end=10,
                                     margin_top=8, margin_bottom=10)
        self.chart.set_draw_func(self._draw_chart)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        right.append(reading)
        right.append(tiles_row)
        right.append(self.chart)

        split = Gtk.Box(spacing=0)
        split.append(settings)
        split.append(right)

        # ---- status strip along the bottom
        self.status = Gtk.Label(label="connecting…", xalign=0)
        self.sensor_status = Gtk.Label(xalign=0)
        self.sensor_status.add_css_class("mono")
        self.clock = Gtk.Label(xalign=1, hexpand=True)
        self.clock.add_css_class("mono")
        bar = ui.status_bar()
        bar.append(self.status)
        bar.append(self.sensor_status)
        bar.append(self.clock)
        self._tick_clock()
        GLib.timeout_add_seconds(1, self._tick_clock)

        self.toasts = Adw.ToastOverlay(child=split)
        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(self.toasts)
        view.add_bottom_bar(bar)
        self.set_content(view)

    def _tick_clock(self) -> bool:
        self.clock.set_text(time.strftime("%Y-%m-%d  %H:%M:%S"))
        return True

    # --- daemon ---------------------------------------------------------------------------------

    def _reader(self):
        """Worker thread: talk to the meter, hand each reading to the UI thread."""
        while not self._stop:
            if not self.connected:
                try:
                    pm = self.meter.info()
                except Exception as e:  # noqa: BLE001
                    GLib.idle_add(self.status.set_text, f"meter: {str(e)[:60]}")
                    time.sleep(1.0)
                    continue
                self.connected = True
                GLib.idle_add(self._on_connected, pm)
            try:
                r = self.meter.read(n=int(self.averaging.get_value()))
            except Exception as e:  # noqa: BLE001
                self.connected = False
                GLib.idle_add(self.status.set_text, f"lost meter: {str(e)[:50]}")
                continue
            GLib.idle_add(self._on_reading, r)

    def _on_connected(self, pm):
        self.wavelength.handler_block_by_func(self._on_wavelength)
        lo, hi = pm.get("wavelength_range_nm", [300, 2000])
        self.wavelength.set_range(lo, hi)
        self.wavelength.set_value(pm["wavelength_nm"])
        self.wavelength.handler_unblock_by_func(self._on_wavelength)
        wanted = self._prefs.get("wavelength_nm")
        if wanted and lo <= wanted <= hi and abs(wanted - pm["wavelength_nm"]) > 0.5:
            self.wavelength.set_value(wanted)      # restore the last-used wavelength (applies via _on_wavelength)
        self.device_name.set_text(pm["idn"].split(",")[1].strip() if "," in pm["idn"] else pm["idn"][:24])
        ui.set_state(self.device_dot, "ok")
        self.status.set_text("connected")
        self._show_meter_state(pm)
        return False

    def _show_meter_state(self, pm: dict) -> bool:
        """Reflect what the meter itself reports: its toggles, and the numbers only it knows."""
        self._syncing = True           # setting these from the meter must not send the setting back
        try:
            for button, key in ((self.relative, "relative"), (self.autorange, "auto_range")):
                if key in pm and button.get_active() != bool(pm[key]):
                    button.set_active(bool(pm[key]))
        finally:
            self._syncing = False
        self.zeroed = bool(pm.get("zeroed"))
        sensor = pm.get("sensor", {})
        parts = [f"{sensor.get('name', '?')} #{sensor.get('serial', '?')}", f"calibrated {sensor.get('calibration_date', '?')}"]
        if pm.get("responsivity_a_per_w"):
            parts.append(f"responsivity {pm['responsivity_a_per_w'] * 1e3:.3f} mA/W")
        if pm.get("amps") is not None:
            parts.append(f"photocurrent {pm['amps'] * 1e9:.3f} nA")
        if pm.get("dark_level_w"):
            parts.append("dark level {} {}".format(*format_watts(pm["dark_level_w"])))
        if pm.get("range_w"):
            parts.append("range {} {}{}".format(*format_watts(pm["range_w"]), "" if pm.get("auto_range") else ", fixed"))
        self.meter_label.set_text("\n".join(parts))
        self.sensor_status.set_text(f"{sensor.get('name', '?')} #{sensor.get('serial', '?')}")
        return False

    def _on_reading(self, r) -> bool:
        w = r["watts"]
        now = time.time()
        self.history.append((now, w))
        while self.history and now - self.history[0][0] > self.history_s:
            self.history.popleft()
        s = self.stats
        s["min"], s["max"] = min(s["min"], w), max(s["max"], w)
        s["sum"] += w
        s["n"] += 1
        if self.dbm.get_active():
            dbm = r.get("dbm")
            num, unit = (f"{dbm:.2f}", "dBm") if dbm is not None else ("—", "dBm")
        else:
            num, unit = format_watts(w)
        self.value.set_markup(f'<span size="42000">{GLib.markup_escape_text(num)}</span>')
        self.unit.set_text(unit)
        notes = [f"{r['wavelength_nm']:.0f} nm"]
        if getattr(self, "zeroed", False):
            notes.append("zeroed")
        if self.relative.get_active():
            notes.append("relative")
        self.sub.set_text("   ·   ".join(notes))
        self.live.set_visible(True)
        peak = max(abs(v) for _, v in self.history) or 1.0
        self.bar.set_value(min(abs(w) / peak, 1.0))
        for name, value in (("Maximum", s["max"]), ("Minimum", s["min"]), ("Mean", s["sum"] / s["n"]),
                            ("Std dev", r["std_watts"])):
            number, unit_label = self.tiles[name]
            text, tile_unit = format_watts(value)
            number.set_text(text)
            unit_label.set_text(tile_unit)
        self.tiles["Samples"][0].set_text(str(s["n"]))
        self.tiles["Samples"][1].set_text("reads")
        if self.log_writer:
            self.log_writer.writerow([f"{now:.3f}", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
                                      f"{w:.6e}", f"{r['std_watts']:.3e}", r["wavelength_nm"]])
        self.chart.queue_draw()
        return False

    def _load_prefs(self) -> dict:
        try:
            return json.loads(SETTINGS_FILE.read_text())
        except (OSError, ValueError):
            return {}

    def _save_prefs(self, **changes):
        self._prefs.update(changes)
        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps(self._prefs))
        except OSError:
            pass

    def _on_wavelength(self, spin):
        self._pending_wavelength = spin.get_value()
        self._save_prefs(wavelength_nm=spin.get_value())
        threading.Thread(target=self._apply_wavelength, daemon=True).start()

    def _apply_wavelength(self):
        try:
            self.meter.set(wavelength_nm=self._pending_wavelength)
        except Exception as e:  # noqa: BLE001
            GLib.idle_add(self.status.set_text, str(e)[:60])

    def _zero_on(self, meter):
        return meter.zero(True)

    def _zero_off(self, meter):
        return meter.zero(False)

    def _set_reference(self, meter):
        """The present reading becomes the reference, and relative mode goes on."""
        reference = self.history[-1][1] if self.history else meter.read()["watts"]
        return meter.set(reference_w=reference, relative=True)

    def _apply_async(self, action):
        """Settings run off the UI thread; the backend serialises them against the reader."""
        def work():
            try:
                state = action(self.meter)
                self.stats = self._fresh_stats()
                if isinstance(state, dict):
                    GLib.idle_add(self._show_meter_state, state)
            except Exception as e:  # noqa: BLE001
                GLib.idle_add(self.status.set_text, str(e)[:60])
        threading.Thread(target=work, daemon=True).start()

    def _on_log_toggled(self, button):
        if button.get_active():
            path = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOCUMENTS) or GLib.get_home_dir()
            name = f"{path}/power-{time.strftime('%Y%m%d-%H%M%S')}.csv"
            self.log_file = open(name, "w", newline="")
            self.log_writer = csv.writer(self.log_file)
            self.log_writer.writerow(["unix_time", "local_time", "watts", "std_watts", "wavelength_nm"])
            button.set_tooltip_text(f"Logging to {name}")
        elif self.log_file:
            self.log_file.close()
            self.log_file = self.log_writer = None
            button.set_tooltip_text("Log readings to a CSV file")

    @staticmethod
    def _fresh_stats():
        return {"min": float("inf"), "max": float("-inf"), "sum": 0.0, "n": 0}

    # --- chart ----------------------------------------------------------------------------------

    def _draw_chart(self, area, cr, width, height):
        colour = area.get_color()
        accent = Gdk.RGBA()
        accent.parse("#3f8fd8")
        plot.draw_series(cr, width, height, list(self.history), colour=colour, accent=accent,
                         window_s=self.history_s, format_value=lambda v: " ".join(format_watts(v)))


def main(host: str, port: int) -> int:
    """The window on a meter owned by an oclab-rig daemon."""
    app = Adw.Application(application_id="za.ac.wits.oclab.PowerMeter")
    app.connect("activate", lambda a: PowerMeterWindow(a, DaemonMeter(host, port)).present())
    return app.run([])


def main_direct(argv: list[str] | None = None) -> int:
    """The window on the meter plugged into this machine: the `thorlabs-pm-gui` command."""
    import argparse
    parser = argparse.ArgumentParser(prog="thorlabs-pm-gui", description="Thorlabs power meter window")
    parser.add_argument("--serial", help="which meter, when several are plugged in")
    parser.add_argument("--sim", action="store_true", help="a simulated meter, to see the window without hardware")
    args = parser.parse_args(argv)
    # Its own id, so its launcher does not collide with the rig's daemon-backed Power Meter on a lab PC.
    app = Adw.Application(application_id="za.ac.wits.oclab.ThorlabsPowerMeter")
    app.connect("activate", lambda a: PowerMeterWindow(a, DirectMeter(args.serial, simulated=args.sim)).present())
    return app.run([])
