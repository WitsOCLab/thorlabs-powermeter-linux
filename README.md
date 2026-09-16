# thorlabs-powermeter-linux

Thorlabs PM16, PM160, PM100 and PM400-family optical power meters on Linux, through the kernel's
own `usbtmc` driver. No VISA, no National Instruments runtime, no vendor DLL.

```
pip install thorlabs-powermeter-linux
thorlabs-pm watch --wavelength-nm 532
```
```python
from thorlabs_pm import PowerMeter
```

## The problem it solves

Thorlabs' Optical Power Monitor and the TLPM library are Windows-only. The meters themselves
are ordinary USBTMC instruments speaking SCPI, so on Linux the kernel driver is all that is
needed — but the details (a udev rule for the device node, a stable name per serial number,
timeouts, unsticking a stalled pipe, checking `SYST:ERR?` after every command, and the meter's
own zero / relative / range modes) are what every lab rediscovers. This is that, done once.

## What it does

- finds meters by serial number, with a stable `/dev/thorlabs-pm/<serial>` symlink from the udev rule
- readings in watts with the standard deviation over *n* samples, and dBm
- wavelength, averaging, manual or automatic range, the meter's dark-level zero, relative mode against a stored reference
- every command checked against the instrument's error queue, so a bad setting fails where it happens
- identity, sensor head, calibration date and responsivity from the instrument
- `thorlabs-pm` command line: `list`, `read`, `watch`, `set`, `info`, all with `--json`
- a simulator with the same interface for tests without a meter

Tested with a PM16-121. Other heads in the same SCPI family should work; reports welcome.

## Setup

Copy `udev/60-thorlabs-pm.rules` to `/etc/udev/rules.d/`, `sudo udevadm control --reload-rules`,
and add your user to the `plugdev` group. Plug the meter in; `thorlabs-pm list` shows it.

## Roadmap

The Linux replacement for the Optical Power Monitor window — live reading, statistics, chart,
CSV logging — exists in the Wits OCLab rig software and will be made standalone here.
