from gpiozero import Button
from signal import pause
import subprocess
import time

BUTTON_PIN = 21

button = Button(BUTTON_PIN, pull_up=True, hold_time = 2, bounce_time=0.2)

def shutdown():
    print("[Shutdown] shutdown button pressed...") 
    time.sleep(0.5)  
    #subprocess.run(["sudo", "shutdown", "-h", "now"])


button.when_pressed = shutdown

print(f"[Shutdown] listening for shutdown button on GPIO{BUTTON_PIN}...")

pause()