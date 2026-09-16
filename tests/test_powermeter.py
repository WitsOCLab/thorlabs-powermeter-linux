"""Without a meter: device discovery against a fake sysfs, and the command line."""
import io
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from thorlabs_pm import cli, powermeter


class FindTest(unittest.TestCase):
    def test_finds_thorlabs_devices_by_vendor_and_serial(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            usb = root / "1-3.1"
            (usb / "1-3.1:1.0").mkdir(parents=True)
            (usb / "idVendor").write_text("1313\n")
            (usb / "serial").write_text("18090634\n")
            (usb / "product").write_text("PM16-121\n")
            node = root / "usbtmc7"
            node.mkdir()
            os.symlink(usb / "1-3.1:1.0", node / "device")
            other = root / "2-1"
            (other / "2-1:1.0").mkdir(parents=True)
            (other / "idVendor").write_text("0957\n")
            node2 = root / "usbtmc8"
            node2.mkdir()
            os.symlink(other / "2-1:1.0", node2 / "device")
            with mock.patch.object(powermeter.glob, "glob", return_value=[str(node), str(node2)]):
                found = powermeter.find_usbtmc()
                by_serial = powermeter.find_usbtmc(serial="18090634")
                missing = powermeter.find_usbtmc(serial="1")
        self.assertEqual(found, [{"path": "/dev/usbtmc7", "serial": "18090634", "product": "PM16-121"}])
        self.assertEqual(by_serial, found)
        self.assertEqual(missing, [])


class CliTest(unittest.TestCase):
    def test_list_prints_each_meter(self):
        with mock.patch.object(cli, "find_usbtmc", return_value=[{"path": "/dev/usbtmc1", "serial": "18090634", "product": "PM16-121"}]), \
             mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(cli.main(["list"]), 0)
        self.assertIn("18090634", out.getvalue())
        self.assertIn("/dev/usbtmc1", out.getvalue())

    def test_read_formats_watts_with_si_prefix(self):
        meter = mock.Mock()
        meter.read.return_value = {"watts": 4.117e-10, "std_watts": 2e-12, "wavelength_nm": 532.0, "n": 1, "dbm": None}
        with mock.patch.object(cli, "PowerMeter", return_value=meter), \
             mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(cli.main(["read", "-n", "1"]), 0)
        self.assertIn("411.700 pW", out.getvalue())
        meter.close.assert_called_once()

    def test_no_meter_is_an_error_not_a_traceback(self):
        with mock.patch.object(cli, "PowerMeter", side_effect=LookupError("no Thorlabs usbtmc device")), \
             mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            self.assertEqual(cli.main(["info"]), 1)
        self.assertIn("no Thorlabs", err.getvalue())

    def test_si(self):
        self.assertEqual(cli.si(0.0012), "1.200 mW")
        self.assertEqual(cli.si(2.5e-9), "2.500 nW")


if __name__ == "__main__":
    unittest.main()
