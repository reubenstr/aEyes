import serial
import time

PORT = "/dev/ttyAMA3"
BAUD = 115200

ser = serial.Serial(
    port=PORT,
    baudrate=BAUD,
    timeout=1
)

time.sleep(0.5)

print("UART loopback test running... Ctrl+C to stop")

counter = 0
try:
    while True:
        msg = f"PING {counter}\n"
        ser.write(msg.encode("ascii"))

        rx = ser.readline().decode("ascii", errors="ignore")

        if rx == msg:
            print("OK:", rx.strip())
        else:
            print("ERR: sent:", msg.strip(), "recv:", rx.strip())

        counter += 1
        time.sleep(0.5)

except KeyboardInterrupt:
    print("\nStopped")

ser.close()
