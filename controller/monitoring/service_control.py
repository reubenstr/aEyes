"""Only the controller's fixed systemd unit can be restarted."""
import asyncio
import os

UNIT = "main.service"


class ServiceControl:
    def __init__(self, enabled=None):
        self.enabled = enabled if enabled is not None else os.getenv("AEYES_SERVICE_CONTROL") == "1"
        self.status = "unknown"
        self.error = None
        self.restarting = False

    async def inspect(self):
        if not self.enabled or self.restarting:
            return
        try:
            process = await asyncio.create_subprocess_exec(
                "/usr/bin/systemctl", "show", UNIT, "--property=ActiveState", "--value",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            try:
                output, _ = await asyncio.wait_for(process.communicate(), 3)
                self.status = output.decode().strip() or "unknown"
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
        except OSError as error:
            self.error = str(error)

    async def restart(self):
        self.error = None
        try:
            process = await asyncio.create_subprocess_exec(
                "/usr/bin/sudo", "-n", "/usr/bin/systemctl", "restart", UNIT,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            try:
                _, stderr = await asyncio.wait_for(process.communicate(), 20)
                if process.returncode:
                    raise RuntimeError(stderr.decode().strip() or "Controller restart failed")
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
        except Exception as error:
            self.error = str(error)
        finally:
            self.restarting = False
        await self.inspect()
