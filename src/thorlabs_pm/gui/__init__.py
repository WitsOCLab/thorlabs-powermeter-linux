"""GTK4/libadwaita desktop apps. The rig's windows talk to its daemon; the Power Meter window can also open the instrument itself."""

from __future__ import annotations

import sys


def require_gtk():
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: F401
    except (ImportError, ValueError) as e:
        sys.exit("The GUI needs GTK 4 and libadwaita Python bindings: sudo apt install python3-gi gir1.2-adw-1, "
                 f"and a venv created with --system-site-packages ({e})")
    # The windows use libadwaita 1.5 widgets (AlertDialog; ToolbarView and SpinRow are 1.4).
    # Ubuntu 22.04 ships 1.1: the daemon, CLI and MATLAB client still work there, the apps do not.
    have = (Adw.get_major_version(), Adw.get_minor_version())
    if have < (1, 5):
        sys.exit(f"The GUI needs libadwaita 1.5 or newer; this system has {have[0]}.{have[1]} "
                 "(Ubuntu/Pop!_OS 24.04 or later). The daemon and CLI do not need it.")
    return Adw, Gdk, GLib, Gtk


def format_watts(w: float) -> tuple[str, str]:
    """(number, unit) with an SI prefix so the digits stay readable, like the Thorlabs display."""
    if w == 0:
        return "0.000", "W"
    for unit, scale in (("W", 1), ("mW", 1e3), ("µW", 1e6), ("nW", 1e9), ("pW", 1e12)):
        if abs(w) * scale >= 1:
            return f"{w * scale:.3f}", unit
    return f"{w * 1e12:.3f}", "pW"
