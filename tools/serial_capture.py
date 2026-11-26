"""Read an ESP32 serial port for a fixed time, then exit (pio device monitor never exits).

Usage (run with PlatformIO's Python, which has pyserial):
    ~/.platformio/penv/bin/python tools/serial_capture.py [--port /dev/cu.usbmodem2101] [--seconds 8] [--reset]

--reset pulses RTS to reboot the board first, so you catch the boot log.
"""
import argparse
import glob
import sys
import time

import serial

p = argparse.ArgumentParser()
p.add_argument("--port", default=None)
p.add_argument("--baud", type=int, default=115200)
p.add_argument("--seconds", type=float, default=8)
p.add_argument("--reset", action="store_true")
a = p.parse_args()

port = a.port or next(iter(sorted(glob.glob("/dev/cu.usbmodem*"))), None)
if not port:
    sys.exit("No /dev/cu.usbmodem* port found. Is the board plugged in?")

end = time.time() + a.seconds
with serial.Serial(port, a.baud, timeout=0.2) as s:
    if a.reset:
        s.dtr = False
        s.rts = True
        time.sleep(0.1)
        s.rts = False
        s.close()
        # The USB port drops and comes back after a reset; reopen it.
        while time.time() < end:
            time.sleep(0.3)
            try:
                s.open()
                break
            except serial.SerialException:
                pass
    while time.time() < end:
        try:
            data = s.read(4096)
        except serial.SerialException:
            time.sleep(0.3)
            try:
                s.close(); s.open()
            except serial.SerialException:
                pass
            continue
        if data:
            sys.stdout.write(data.decode("utf-8", "replace"))
            sys.stdout.flush()
