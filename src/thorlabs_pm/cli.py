"""`thorlabs-pm`: the meter from the shell - list, read, watch, set, info."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

from .powermeter import PowerMeter, find_usbtmc

_UNITS = (("W", 1.0), ("mW", 1e3), ("µW", 1e6), ("nW", 1e9), ("pW", 1e12))


def si(watts: float) -> str:
    """Watts with an SI prefix, the way the meter's own display shows them."""
    for unit, scale in _UNITS:
        if abs(watts) * scale >= 1:
            return f"{watts * scale:.3f} {unit}"
    return f"{watts * 1e12:.3f} pW"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="thorlabs-pm",
                                description="Thorlabs PM16 / PM160 / PM100-family power meters over the Linux usbtmc driver.")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="meters found on the USB bus")
    for name, text in (("read", "one reading"), ("watch", "live readings until Ctrl-C")):
        s = sub.add_parser(name, help=text)
        s.add_argument("--serial", help="which meter, when several are plugged in")
        s.add_argument("-n", type=int, default=1, help="readings to average (default 1)")
        s.add_argument("--wavelength-nm", type=float, help="set the wavelength first")
        s.add_argument("--json", action="store_true", help="machine-readable output")
    s = sub.add_parser("set", help="wavelength, auto-range, dark-level zero")
    s.add_argument("--serial")
    s.add_argument("--wavelength-nm", type=float)
    s.add_argument("--auto-range", choices=["on", "off"])
    s.add_argument("--zero", choices=["on", "off"], help="on: store the present reading as the dark level")
    s = sub.add_parser("info", help="identity, sensor head, calibration date, current settings")
    s.add_argument("--serial")
    sub.add_parser("desktop-install", help="put the Power Meter app in this user's application menu")
    return p


def desktop_install() -> int:
    """Copy the launcher and icon into the user's freedesktop directories and refresh the caches."""
    import shutil
    import subprocess
    from importlib import resources
    home = pathlib.Path.home()
    apps = home / ".local/share/applications"
    icons = home / ".local/share/icons/hicolor/scalable/apps"
    apps.mkdir(parents=True, exist_ok=True)
    icons.mkdir(parents=True, exist_ok=True)
    data = resources.files("thorlabs_pm") / "data"
    launcher = data / "za.ac.wits.oclab.ThorlabsPowerMeter.desktop"
    text = launcher.read_text()
    exe = shutil.which("thorlabs-pm-gui")
    if exe:
        text = text.replace("Exec=thorlabs-pm-gui", f"Exec={exe}")     # menus do not search a pipx PATH
    (apps / launcher.name).write_text(text)
    shutil.copy(str(data / "za.ac.wits.oclab.ThorlabsPowerMeter.svg"), icons)
    index = home / ".local/share/icons/hicolor/index.theme"
    if not index.exists():   # some icon loaders skip a theme directory without one
        index.write_text("[Icon Theme]\nName=Hicolor\nComment=Fallback icon theme\nHidden=true\nDirectories=scalable/apps\n\n"
                         "[scalable/apps]\nSize=128\nMinSize=16\nMaxSize=512\nContext=Applications\nType=Scalable\n")
    for cmd in (["update-desktop-database", str(apps)], ["gtk4-update-icon-cache", "-f", "-t", str(index.parent)]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, capture_output=True)
    print(f"installed {apps / launcher.name}; 'Power Meter' is in the application menu (log out and in if not)")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "desktop-install":
        return desktop_install()
    if args.command == "list":
        found = find_usbtmc()
        if not found:
            print("no Thorlabs usbtmc device: is the meter plugged in, and the udev rule installed?", file=sys.stderr)
            return 1
        for d in found:
            print(f"{d['serial']:12} {d['product']:18} {d['path']}")
        return 0
    try:
        pm = PowerMeter(serial=args.serial, wavelength_nm=getattr(args, "wavelength_nm", None))
    except LookupError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    try:
        if args.command == "info":
            print(json.dumps(pm.describe(), indent=2))
        elif args.command == "set":
            state = pm.configure(wavelength_nm=args.wavelength_nm,
                                 auto_range=None if args.auto_range is None else args.auto_range == "on")
            if args.zero:
                state = pm.zero(args.zero == "on")
            print(json.dumps(state, indent=2))
        elif args.command == "read":
            r = pm.read(n=args.n)
            print(json.dumps(r) if args.json else f"{si(r['watts'])}   ±{si(r['std_watts'])}   {r['wavelength_nm']:.0f} nm")
        else:
            try:
                while True:
                    r = pm.read(n=args.n)
                    if args.json:
                        print(json.dumps({"time": time.time(), **r}), flush=True)
                    else:
                        print(f"\r{time.strftime('%H:%M:%S')}  {si(r['watts']):>14}   ±{si(r['std_watts'])}   "
                              f"{r['wavelength_nm']:.0f} nm   ", end="", flush=True)
            except KeyboardInterrupt:
                print()
    finally:
        pm.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
