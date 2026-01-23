import threading

from pathlib import Path

from eye import Eye
from eye_controller import EyeController


if __name__ == "__main__":
    from pathlib import Path
    import threading

    ROOT = Path(__file__).resolve().parent

    app = Eye(
        vert_path=ROOT / "shaders" / "eye.vert",
        frag_path=ROOT / "shaders" / "eye.frag",       
        update_hz=60.0,
    )

    controller = EyeController(app)
    ctrl_thread = threading.Thread(
        target=controller.run,
        daemon=True
    )
    ctrl_thread.start()

    def shutdown():
        print("\nShutting down…")
        controller.stop()
        try:
            app.window.close()
        except Exception:
            pass

    app.window.on_close = shutdown

    try:
        app.run()  # blocks
    except KeyboardInterrupt:
        shutdown()

