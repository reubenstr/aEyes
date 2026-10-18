"""Reachability is deliberately separate from application/motor health."""

import asyncio
import time


async def ping_eye(eye_id):
    address = f"192.168.5.{100 + eye_id}"
    started = time.monotonic()
    process = None
    status = "unknown"
    try:
        process = await asyncio.create_subprocess_exec(
            "ping",
            "-n",
            "-c",
            "1",
            "-W",
            "1",
            address,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        result = await asyncio.wait_for(process.wait(), 1.2)
        status = "reachable" if result == 0 else "unreachable"
    except asyncio.TimeoutError:
        status = "unreachable"
    except OSError:
        pass
    finally:
        if process and process.returncode is None:
            process.kill()
            await process.wait()
    return {
        "eye_id": eye_id,
        "address": address,
        "status": status,
        "probe_ms": round((time.monotonic() - started) * 1000, 1),
        "application": "unknown",
        "motors": "unknown",
    }


async def check_eyes():
    return await asyncio.gather(*(ping_eye(i) for i in range(1, 7)))
