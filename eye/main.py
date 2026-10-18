import os
import math
import signal
import sys
import zmq
import json
from eye_renderer import EyeRenderer, TextType
from threading import Thread, Event
from time import sleep, monotonic

from data_types import ControlMessage
from motors.data_types import MotorName, MotorSpeeds
from motors.motors import Motors
from motors.motor_config import get_motor_info, BASE_HOME_INVERSION, EYE_INVERSIONS

SOCKET_ADDRESS = "192.168.5.100"
SOCKET_PORT = 9000
MESSAGE_TIMEOUT_SECONDS = 3.0

class Eye:
    def __init__(self):
        self.eye_id = None
        self.motors = None
        self.socket = None
        self.thread_handle = None
        self.exit_event = Event()
        self.commanded_yaw = 0.0
        self.commanded_pitch = 0.0

    ###############################################################################
    # Initializers
    ###############################################################################

    def init_eye_renderer(self):
        print("[Main] init eye renderer")
        self.eye_renderer = EyeRenderer()
        self.eye_renderer.window.on_close = self.shutdown
        self.eye_renderer.set_text(TextType.INFO, "Waiting for data.")

    def _init_local(self):
        print("[Main] initialize local variables")
        eye_id = os.getenv("EYE_ID", None)
        if eye_id is None:
            self.eye_renderer.set_text(TextType.ERROR, "EYE_ID not found in ENV vars!")
        else:
            self.eye_id = int(eye_id)

    def _init_motors(self):
        try:
            self.motors = Motors(allow_enable=True)
            if self.eye_id and EYE_INVERSIONS[self.eye_id]:
                for name in (MotorName.BASE, MotorName.EYE):
                    self.motors.set_inversion_rotation(name, not self.motors.get_inverse_rotation(name))
            if self.exit_event.is_set():
                raise RuntimeError("Motor startup cancelled")
            if not self.motors.enable_all_motors():
                raise RuntimeError("Motor enable failed")
            return self.home_motors(self.motors)
        except Exception as error:
            if self.motors is not None:
                try:
                    self.motors.disable_all_motors()
                except Exception as stop_error:
                    print(f"[Main] Motor disable failed: {stop_error}")
            self.eye_renderer.set_text(TextType.ERROR, f"Motor startup failed: {error}")
            return False

    def _init_socket(self):
        print("[Main] init zmq")
        context = zmq.Context()
        self.socket = context.socket(zmq.SUB)
        self.socket.setsockopt(zmq.CONFLATE, 1)
        address = f"tcp://{SOCKET_ADDRESS}:{SOCKET_PORT}"
        self.socket.connect(address)
        self.socket.setsockopt_string(zmq.SUBSCRIBE, "")
        print(f"[Main] Socket requested at address: {address}")

    ###############################################################################
    # Helpers
    ###############################################################################

    def _flush_socket(self):
        try:
            while True and self.socket is not None:
                self.socket.recv_string(flags=zmq.NOBLOCK)
        except zmq.Again:
            pass

    def ramp_target(self, commanded: float, target: float, dt: float) -> float:
        CLOSE_DEG = 5.0  # below this → pass-through (fast tracking)
        FAR_DEG = 30.0  # above this → max slowdown
        FAST_DEG_S = 900.0  # deg/sec when close (~pass-through)
        SLOW_DEG_S = 22.5  # deg/sec when far   (smooth slew)
        if not all(math.isfinite(v) for v in (commanded, target, dt)) or dt < 0:
            raise ValueError("Motor ramp values must be finite and dt nonnegative")
        delta = abs(target - commanded)
        t = max(0.0, min(1.0, (delta - CLOSE_DEG) / (FAR_DEG - CLOSE_DEG)))
        t = 3 * t**2 - 2 * t**3  # smoothstep
        max_step = (FAST_DEG_S + t * (SLOW_DEG_S - FAST_DEG_S)) * dt
        return commanded + max(-max_step, min(max_step, target - commanded))

    ###############################################################################
    # Motor Utilities
    ###############################################################################

    def home_motors(self, motors: Motors) -> bool:
        """Calibrate only after both axes stop with fresh CAN position feedback."""
        names = (MotorName.BASE, MotorName.EYE)
        max_sample_age = 0.25
        stable_duration = 0.5
        stable_degrees = 0.25

        def read_sample(name, wait_s=0.):
            deadline = monotonic() + wait_s
            while True:
                sample = motors.get_position_sample(name)
                now = monotonic()
                if (sample is not None and all(math.isfinite(v) for v in sample)
                        and 0 <= now - sample[2] <= max_sample_age):
                    return sample
                if now >= deadline or self.exit_event.is_set():
                    raise RuntimeError(f"Missing/stale position feedback for {name}")
                sleep(0.01)

        self.eye_renderer.set_text(TextType.INFO, "Homing motors...")
        try:
            # Enable sequencing holds the CAN lock; let workers refresh samples
            # before treating the pre-enable cached positions as a fault.
            samples = {name: read_sample(name, wait_s=0.5) for name in names}
            anchors = {name: (sample[0], sample[2]) for name, sample in samples.items()}
            previous_times = {name: sample[2] for name, sample in samples.items()}
            homed = set()
            for name in names:
                direction = -1 if name == MotorName.BASE and BASE_HOME_INVERSION[self.eye_id] else 1
                motors.set_enforce_position_limits(name, False)
                motors.set_motor_targets(name, MotorSpeeds.SLOW, samples[name][1] + direction * 180.)
            deadline = monotonic() + 5.
            sleep(0.5)
            while monotonic() < deadline:
                if self.exit_event.is_set():
                    raise RuntimeError("Homing cancelled")
                for name in names:
                    sample = read_sample(name)
                    samples[name] = sample
                    if sample[2] <= previous_times[name]:
                        continue  # Cached samples never prove that a motor has stopped.
                    previous_times[name] = sample[2]
                    anchor_pos, anchor_time = anchors[name]
                    # Cumulative displacement prevents slow motion being called a stop.
                    if abs(sample[0] - anchor_pos) > stable_degrees:
                        anchors[name] = (sample[0], sample[2])
                        homed.discard(name)
                    elif sample[2] - anchor_time >= stable_duration:
                        if name not in homed:
                            motors.set_motor_targets(name, MotorSpeeds.SLOW, sample[1])
                        homed.add(name)
                if len(homed) == len(names):
                    break
                sleep(0.05)
            if len(homed) != len(names):
                raise RuntimeError("Homing timed out before both motors stopped")

            # Recheck both before changing either calibration.
            samples = {name: read_sample(name) for name in names}
            if any(abs(samples[name][0] - anchors[name][0]) > stable_degrees for name in names):
                raise RuntimeError("Motor moved after homing stop")
            offsets = {}
            for name in names:
                home_position = get_motor_info(name).home_position
                if name == MotorName.BASE and BASE_HOME_INVERSION[self.eye_id]:
                    home_position = -home_position
                offsets[name] = home_position - samples[name][0]
            motors.apply_home_offsets(offsets, MotorSpeeds.SLOW)
            sleep(3.)
            return True
        except Exception as error:
            try:
                motors.disable_all_motors()
            except Exception as stop_error:
                print(f"[Main] Motor disable failed: {stop_error}")
            self.eye_renderer.set_text(TextType.ERROR, f"Homing failed: {error}")
            return False
        finally:
            for name in names:
                motors.set_enforce_position_limits(name, True)

    ###############################################################################
    # Thread
    ###############################################################################

    def _start(self):
        print(f"[Main] worker thread starting")
        if self.exit_event.is_set():
            return
        self.thread_handle = Thread(target=self._worker)
        self.thread_handle.start()

    def stop(self):
        print(f"[Main] worker thread stoping")
        self.exit_event.set()
        if self.thread_handle and self.thread_handle.is_alive():
            self.thread_handle.join()

    def _worker(self):
        last_msg_time = last_tick = monotonic()
        connected = False
        targets = (self.commanded_yaw, self.commanded_pitch)
        self.eye_renderer.set_text(TextType.INFO, "Waiting for data")
        self._flush_socket()
        while not self.exit_event.is_set():
            if self.socket:
                try:
                    payload = json.loads(self.socket.recv_string(flags=zmq.NOBLOCK))
                    msg = ControlMessage(**payload[str(self.eye_id)])
                    if not all(math.isfinite(v) for v in (msg.yaw, msg.pitch)):
                        raise ValueError("Non-finite motor target")
                    targets = tuple(max(get_motor_info(name).min_position,
                                        min(get_motor_info(name).max_position, value))
                                    for name, value in zip((MotorName.BASE, MotorName.EYE), (msg.yaw, msg.pitch)))
                    last_msg_time = monotonic()
                    connected = True
                    self.eye_renderer.set_text(TextType.INFO, "")
                    self.eye_renderer.apply_control_message(msg)
                except zmq.Again:
                    pass
                except (ValueError, TypeError, KeyError) as error:
                    print(f"[Main] Bad message: {error}")
            now = monotonic()
            dt = min(0.1, max(0., now - last_tick))
            last_tick = now
            if connected and now - last_msg_time > MESSAGE_TIMEOUT_SECONDS:
                connected = False
                self.eye_renderer.set_text(TextType.ERROR, "Data timeout!")
            if connected and self.motors:
                self.commanded_yaw = self.ramp_target(self.commanded_yaw, targets[0], dt)
                self.commanded_pitch = self.ramp_target(self.commanded_pitch, targets[1], dt)
                self.motors.set_motor_targets(MotorName.BASE, MotorSpeeds.FAST, self.commanded_yaw)
                self.motors.set_motor_targets(MotorName.EYE, MotorSpeeds.FAST, self.commanded_pitch)
            sleep(0.005)

    ###############################################################################
    # General
    ###############################################################################

    def _deferred_init(self):
        sleep(0.3)  # Allow pyglet event loop to render first frame
        self._init_local()
        if not self.exit_event.is_set() and self.eye_id and self._init_motors() and not self.exit_event.is_set():
            self._init_socket()
            self._start()

    def run(self):
        self.init_eye_renderer()
        Thread(target=self._deferred_init, daemon=True).start()

        # Blocking
        self.eye_renderer.run()

    def shutdown(self):
        self.stop()
        if self.motors:
            try:
                self.motors.shutdown()
            except Exception as e:
                print(f"[Main] Error shutting down motors: {e}")
        try:
            self.eye_renderer.shutdown()
        except Exception as e:
            print(f"[Main] Error shutting down renderer: {e}")


###############################################################################
# Main Entry
###############################################################################
if __name__ == "__main__":
    eye = Eye()
    signal.signal(signal.SIGTERM, lambda sig, frame: (eye.shutdown(), sys.exit(0)))
    try:
        eye.run()
    except KeyboardInterrupt:
        eye.shutdown()
