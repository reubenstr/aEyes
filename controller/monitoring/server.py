"""Standalone API: never imports the camera, tracker, or eye-command publisher."""
import asyncio
from contextlib import asynccontextmanager, suppress
import logging
import os
import time

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict

from .compute import ComputeInspector
from .config_store import ConfigStore, ConflictError
from .contracts import revision
from .eye_health import check_eyes
from .service_control import ServiceControl
from .state import FeedSubscriber, MonitorState

log = logging.getLogger(__name__)


class ConfigWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict
    revision: str


class RestartWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str


def same_origin(origin, scheme, host):
    return origin is None or origin == f"{scheme}://{host}"


def create_app(*, state=None, store=None, service=None, start_workers=True):
    state = state or MonitorState()
    port = int(os.getenv("AEYES_MONITOR_PORT", "8080"))
    store = store or ConfigStore(reserved_ports=(port, 9101))
    service = service or ServiceControl()
    feed = None
    tasks = set()
    mutation_lock = asyncio.Lock()

    async def metrics():
        inspector = ComputeInspector()
        while True:
            try:
                pid = state.describe().get("pid")
                sample = await asyncio.to_thread(inspector.sample, pid)
                with state.lock:
                    state.compute = sample
                await service.inspect()
            except Exception:
                log.exception("Compute/service inspection failed")
            await asyncio.sleep(1)

    async def reachability():
        while True:
            try:
                health = await check_eyes()
                with state.lock:
                    state.health = health
            except Exception:
                log.exception("Reachability probe failed")
            await asyncio.sleep(5)

    @asynccontextmanager
    async def lifespan(app):
        nonlocal feed
        if start_workers:
            feed = FeedSubscriber(state)
            feed.start()
            tasks.update([asyncio.create_task(metrics()), asyncio.create_task(reachability())])
        try:
            yield
        finally:
            pending = list(tasks)
            for task in pending:
                task.cancel()
            for task in pending:
                with suppress(asyncio.CancelledError):
                    await task
            if feed:
                await asyncio.to_thread(feed.close)

    app = FastAPI(title="aEyes monitor", lifespan=lifespan)
    app.state.monitor = state

    @app.middleware("http")
    async def guard_mutations(request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if not same_origin(request.headers.get("origin"), request.url.scheme, request.headers.get("host")):
                return JSONResponse({"detail": "Cross-origin writes are not allowed"}, status_code=403)
        return await call_next(request)

    @app.get("/api/state")
    async def get_state():
        return state.describe(service)

    @app.get("/api/health")
    async def health():
        current = state.describe(service)
        return {"status": "ok", "source": current["source"], "controller": current["controller"], "camera": current["camera"]}

    @app.websocket("/api/ws")
    async def websocket(websocket: WebSocket):
        scheme = "https" if websocket.url.scheme == "wss" else "http"
        if not same_origin(websocket.headers.get("origin"), scheme, websocket.headers.get("host")):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            while True:
                # A slow socket is disconnected, never buffered into an unbounded queue.
                await asyncio.wait_for(websocket.send_json(state.describe(service)), 2)
                # Receive disconnects as well as sending updates; otherwise a closed
                # client can leave a sender running indefinitely in ASGI servers.
                try:
                    await asyncio.wait_for(websocket.receive_text(), .1)
                except asyncio.TimeoutError:
                    pass
        except (WebSocketDisconnect, asyncio.TimeoutError, RuntimeError):
            with suppress(RuntimeError):
                await websocket.close()

    @app.get("/api/camera.mjpeg")
    async def camera(request: Request):
        async def frames():
            previous = -1
            while not await request.is_disconnected():
                serial, jpeg, timestamp = state.video.preview()
                current = state.describe()
                if (current["camera"]["status"] == "streaming" and jpeg and serial != previous
                        and timestamp is not None and time.monotonic() - timestamp <= 1):
                    previous = serial
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " +
                           str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
                await asyncio.sleep(.04)
        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.get("/api/faces/{face_id}/crop.jpg")
    async def crop(face_id: int, session: str, capture: str):
        current = state.describe()
        if (current["controller"]["status"] != "running"
                or current.get("session_id") != session
                or not any(eye["face_id"] == face_id for eye in current["eyes"])):
            raise HTTPException(404, "Face is not currently assigned")
        jpeg = state.video.crop(session, capture, face_id)
        if jpeg is None:
            raise HTTPException(404, "Face image is unavailable")
        return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    def config_description():
        current = state.describe(service)
        result = store.describe(current["active_config"])
        result.update({"geometry": current["geometry"], "source": current["source"],
                       "restart_available": current["controller"]["restart_available"]})
        return result

    @app.get("/api/config")
    async def config():
        try:
            return await asyncio.to_thread(config_description)
        except (OSError, ValueError) as error:
            raise HTTPException(503, str(error)) from error

    @app.put("/api/config")
    async def save(body: ConfigWrite):
        async with mutation_lock:
            if service.restarting:
                raise HTTPException(409, "Wait for the current restart")
            try:
                await asyncio.to_thread(store.save, body.values, body.revision)
                return await asyncio.to_thread(config_description)
            except ConflictError as error:
                raise HTTPException(409, str(error)) from error
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            except OSError as error:
                raise HTTPException(500, f"Settings were not saved: {error}") from error

    @app.post("/api/controller/restart", status_code=202)
    async def restart(body: RestartWrite):
        async with mutation_lock:
            if not service.enabled:
                raise HTTPException(503, "Restart requires the installed service integration")
            if state.describe()["source"] == "demo":
                raise HTTPException(409, "Restart controls main.service. Restart main.py --demo in its terminal instead.")
            if service.restarting:
                raise HTTPException(409, "A restart is already in progress")
            if revision(await asyncio.to_thread(store.read)) != body.revision:
                raise HTTPException(409, "Saved settings changed before restart")
            service.restarting = True
            task = asyncio.create_task(service.restart())
            tasks.add(task)
            task.add_done_callback(tasks.discard)
            return {"status": "restarting", "revision": body.revision}

    return app
