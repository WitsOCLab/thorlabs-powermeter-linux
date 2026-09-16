"""`thorlabs-pm`: the meter from the shell - list, read, watch, set, info."""

from __future__ import annotations

import argparse
import json
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
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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
