import os
import time
import subprocess
from signal import pause
from gpiozero import Button


BUTTON_PIN = 21
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
script_path = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "scripts/shutdown-eyes.sh"))

button = Button(BUTTON_PIN, pull_up=True, bounce_time=2.0)

def shutdown():
    print(f"[Shutdown] calling shutdown script for eyes at: {script_path}") 
    time.sleep(1);
    subprocess.run(["sudo", script_path])
    print(f"[Shutdown] shutdown controller") 
    time.sleep(1)  
    #subprocess.run(["sudo", "shutdown", "-h", "now"])

button.when_pressed = shutdown

print(f"[Shutdown] listening for shutdown button on GPIO{BUTTON_PIN}...")

pause()