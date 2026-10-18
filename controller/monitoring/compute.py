"""One-second, nonblocking psutil host and controller-process inspection."""

import os
import time
import psutil


class ComputeInspector:
    def __init__(self):
        self.process = None
        psutil.cpu_percent(None)

    def sample(self, pid=None):
        memory = psutil.virtual_memory()
        temperature = None
        try:
            sensors = psutil.sensors_temperatures()
            readings = sensors.get("cpu_thermal") or sensors.get("coretemp") or []
            temperature = readings[0].current if readings else None
        except (AttributeError, OSError):
            pass
        process = None
        if pid:
            try:
                if self.process is None or self.process.pid != pid:
                    self.process = psutil.Process(pid)
                    self.process.cpu_percent(None)
                process = {
                    "pid": pid,
                    "cpu_percent": self.process.cpu_percent(None),
                    "rss_bytes": self.process.memory_info().rss,
                }
            except (psutil.Error, OSError):
                self.process = None
        return {
            "cpu_percent": psutil.cpu_percent(None),
            "ram_used_bytes": memory.total - memory.available,
            "ram_total_bytes": memory.total,
            "ram_percent": memory.percent,
            "temperature_c": temperature,
            "uptime_s": time.time() - psutil.boot_time(),
            "load_average": list(os.getloadavg()),
            "process": process,
        }
