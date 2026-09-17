"""Small things every window was doing slightly differently: remembered size, wrapping
control strips, captioned controls and a plain alert.

Kept thin on purpose. The windows stay ordinary GTK; this is only the shared furniture.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import require_gtk

Adw, Gdk, GLib, Gtk = require_gtk()

STATE_FILE = Path(GLib.get_user_config_dir()) / "oclab-rig" / "windows.json"


def _state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def remember_size(window, key: str, default: tuple[int, int] = (900, 640)) -> None:
    """Open at the size this window was last closed at. The rig room has three very
    different screens, so a window that forgets its size is a nuisance every session."""
    saved = _state().get(key) or {}
    window.set_default_size(int(saved.get("width") or default[0]), int(saved.get("height") or default[1]))
    if saved.get("maximized"):
        window.maximize()

    def save(*_) -> bool:
        width, height = window.get_default_size()
        state = _state()
        state[key] = {"width": width, "height": height, "maximized": window.is_maximized()}
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps(state, indent=1))
        except OSError:
            pass
        return False                     # never swallow the close

    window.connect("close-request", save)


def wrap_box(**kwargs) -> Gtk.FlowBox:
    """A row of controls that wraps onto the next line instead of running off the window.
    libadwaita 1.5 has no WrapBox, and a plain Box clipped the last buttons at 640 px."""
    kwargs.setdefault("column_spacing", 12)
    kwargs.setdefault("row_spacing", 8)
    return Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=99,
                       homogeneous=False, **kwargs)


def labelled(text: str, widget) -> Gtk.Box:
    """A control with a small caption above it."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, halign=Gtk.Align.START)
    box.append(Gtk.Label(label=text, css_classes=["caption", "dim-label"], xalign=0))
    box.append(widget)
    return box


def group(*buttons, linked: bool = True) -> Gtk.Box:
    """Buttons that belong together, drawn as one control."""
    box = Gtk.Box(spacing=0 if linked else 6, valign=Gtk.Align.CENTER,
                  css_classes=["linked"] if linked else [])
    for b in buttons:
        box.append(b)
    return box


def alert(parent, heading: str, body: str) -> None:
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response("ok", "OK")
    dialog.present(parent)


# --- instrument styling --------------------------------------------------------------------

_PROVIDER = None


def apply_instrument_style(window) -> None:
    """Load the instrument stylesheet once per display and mark this window as using it.

    Dark by default because the rig is run in the dark, often through laser safety glasses.
    Set OCLAB_THEME=system to follow the desktop instead.
    """
    global _PROVIDER
    display = Gdk.Display.get_default()
    if display is not None and _PROVIDER is None:
        provider = Gtk.CssProvider()
        provider.load_from_path(str(Path(__file__).with_name("style.css")))
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        _PROVIDER = provider
    window.add_css_class("instrument")
    if os.environ.get("OCLAB_THEME", "dark") != "system":
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)


def panel(*, spacing: int = 8, flat: bool = False, **kwargs) -> Gtk.Box:
    """A boxed region, the unit instrument software is built from."""
    kwargs.setdefault("margin_top", 10)
    kwargs.setdefault("margin_bottom", 10)
    kwargs.setdefault("margin_start", 10)
    kwargs.setdefault("margin_end", 10)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing, **kwargs)
    box.add_css_class("panel-flat" if flat else "panel")
    return box


def panel_title(text: str) -> Gtk.Label:
    label = Gtk.Label(label=text, xalign=0)
    label.add_css_class("panel-title")
    return label


def field(text: str, widget) -> Gtk.Box:
    """A labelled control for a settings column: caption above, control filling the width."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    caption = Gtk.Label(label=text, xalign=0)
    caption.add_css_class("field-label")
    box.append(caption)
    box.append(widget)
    return box


def tile(name: str, unit: str = "") -> tuple[Gtk.Box, Gtk.Label, Gtk.Label]:
    """A statistic tile: small uppercase name, monospaced value, unit. Returns (box, value, unit)."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1, hexpand=True)
    box.add_css_class("tile")
    label = Gtk.Label(label=name, xalign=0)
    label.add_css_class("tile-label")
    value = Gtk.Label(label="—", xalign=0)
    value.add_css_class("tile-value")
    unit_label = Gtk.Label(label=unit, xalign=0)
    unit_label.add_css_class("tile-unit")
    row = Gtk.Box(spacing=4)
    row.append(value)
    row.append(unit_label)
    box.append(label)
    box.append(row)
    return box, value, unit_label


def chip(text: str = "", state: str = "idle") -> tuple[Gtk.Box, Gtk.Label, Gtk.Label]:
    """A pill with a state dot: connected, warning, fault. Returns (box, dot, label)."""
    box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
    box.add_css_class("chip")
    dot = Gtk.Label(label="\u25cf")
    dot.add_css_class(f"dot-{state}")
    label = Gtk.Label(label=text)
    box.append(dot)
    box.append(label)
    return box, dot, label


def set_state(dot: Gtk.Label, state: str) -> None:
    for name in ("dot-ok", "dot-warn", "dot-bad", "dot-idle"):
        dot.remove_css_class(name)
    dot.add_css_class(f"dot-{state}")


def status_bar(**kwargs) -> Gtk.Box:
    box = Gtk.Box(spacing=14, margin_start=10, margin_end=10, margin_top=3, margin_bottom=3, **kwargs)
    box.add_css_class("statusbar")
    return box


def widen(page, maximum: int = 1100) -> None:
    """Let a preferences page use the window.

    libadwaita clamps a preferences page to about 600 px, which is right for settings but
    leaves a wide instrument window two thirds empty. The clamp is not reachable from CSS,
    so it is found in the tree and given a larger maximum.
    """
    def walk(widget, depth=0):
        if widget is None or depth > 6:
            return False
        if isinstance(widget, Adw.Clamp):
            widget.set_maximum_size(maximum)
            widget.set_tightening_threshold(maximum)
            return True
        child = widget.get_first_child()
        found = False
        while child is not None:
            found = walk(child, depth + 1) or found
            child = child.get_next_sibling()
        return found

    walk(page)
