"""Ten readings a second to a CSV file until Ctrl-C."""
import csv
import time

from thorlabs_pm import PowerMeter

with PowerMeter(wavelength_nm=532) as pm, open("power.csv", "w", newline="") as f:
    out = csv.writer(f)
    out.writerow(["unix_time", "watts", "std_watts"])
    try:
        while True:
            r = pm.read(n=1)
            out.writerow([f"{time.time():.3f}", f"{r['watts']:.6e}", f"{r['std_watts']:.3e}"])
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
