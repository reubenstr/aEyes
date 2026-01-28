import threading

from pathlib import Path

from eye import EyeRenderer
from eye_controller import EyeController

from threading import Thread, Event, Lock
from pathlib import Path
from time import sleep
   

class Eye:
    def __init__(self):  
        pass


    def init_eye_renderer(self):
        ROOT = Path(__file__).resolve().parent

        self.eye_renderer = EyeRenderer(
            vert_path=ROOT / "shaders" / "eye.vert",
            frag_path=ROOT / "shaders" / "eye.frag",       
            update_hz=60.0,
        )
    
        self.eye_renderer.window.on_close = self.shutdown
    
    def start(self):
        print(f"[Main] worker thread starting")
        self.exit_event: Event = Event()
        self.thread_handle = Thread(target=self._worker)
        self.thread_handle.start()
        
    def stop(self):
        print(f"[Main] worker thread stoping")
        if self.thread_handle and self.thread_handle.is_alive():
            self.exit_event.set()
            self.thread_handle.join()

    def _worker(self):
        self.exit_event.clear()

        while not self.exit_event.is_set():
            sleep(0.010)

    def run(self):
        self.init_eye_renderer()
        
        self.start()
        
        # Blocking
        self.eye_renderer.run()   
    
    def shutdown(self):
        try:
            self.eye_renderer.window.close()
            self.stop()
        except Exception:
            pass

###############################################################################
# Main Entry
###############################################################################
if __name__ == "__main__":    
    eye = Eye()  
    try:
        eye.run()  
    except KeyboardInterrupt:
        eye.shutdown()

