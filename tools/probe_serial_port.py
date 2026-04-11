from __future__ import annotations

import argparse
import binascii
import time

import serial


def main() -> None:
    parser = argparse.ArgumentParser(description="Send DropMe ping to a serial port and dump raw RX bytes.")
    parser.add_argument("port", help="Serial port name, e.g. COM4")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument("--seconds", type=float, default=3.0, help="Read window after ping (default: 3.0)")
    args = parser.parse_args()

    req = bytes.fromhex("AA 01 00 1E 01")
    print(f"Opening {args.port} @ {args.baud}")
    with serial.Serial(args.port, args.baud, timeout=0.2) as s:
        s.reset_input_buffer()
        s.reset_output_buffer()
        print("Settling port for 1.25s...")
        time.sleep(1.25)
        print("TX", binascii.hexlify(req).decode())
        s.write(req)
        s.flush()

        end = time.time() + args.seconds
        data = bytearray()
        while time.time() < end:
            chunk = s.read(256)
            if chunk:
                data.extend(chunk)
                print("RX", binascii.hexlify(chunk).decode())
            time.sleep(0.05)

    print("TOTAL", binascii.hexlify(data).decode())


if __name__ == "__main__":
    main()
