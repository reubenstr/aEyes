from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from dataclasses import asdict, fields
from pathlib import Path
from typing import get_type_hints
from unittest.mock import MagicMock, patch

from data_types import Color, ControlMessage, EyeState


EYE_DIR = Path(__file__).resolve().parents[1] / "eye"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {name: module}):
        spec.loader.exec_module(module)
    return module


class EyeRenderPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.eye_types = load_module("eye_control_types_test", EYE_DIR / "data_types.py")
        with patch.dict(sys.modules, {"zmq": MagicMock()}):
            cls.publisher_class = load_module("eye_publisher_test", EYE_DIR.parent / "controller" / "publisher.py").Publisher
        pyglet = types.ModuleType("pyglet")
        pyglet.options = MagicMock()
        pyglet.gl = MagicMock()
        shaders = types.ModuleType("pyglet.graphics.shader")
        shaders.Shader = object
        shaders.ShaderProgram = object
        with patch.dict(sys.modules, {"pyglet": pyglet, "pyglet.graphics.shader": shaders,
                                     "data_types": cls.eye_types}):
            cls.renderer_module = load_module("eye_renderer_test", EYE_DIR / "eye_renderer.py")

    def setUp(self) -> None:
        self.state = EyeState(
            eye_id=4, radius=0.9, rotation=13, eye_lid=0.65, yaw=-12, pitch=18,
            iris_color=Color(12, 34, 56), iris_accent_color=Color(22, 44, 66),
            iris_center_color=Color(32, 54, 76), striation_color=Color(42, 64, 86),
            pupil_color=Color(1, 2, 3), sclera_color=Color(201, 202, 203),
            vein_color=Color(174, 23, 24), iris_size=0.4, pupil_size=0.7,
            curvature=0.3, vein_count=17, vein_seed=4, is_cat_eye=True,
        )
        self.message = ControlMessage.from_state(self.state)
        self.renderer = self.renderer_module.EyeRenderer.__new__(self.renderer_module.EyeRenderer)

    def test_both_control_message_definitions_match(self) -> None:
        self.assertEqual([f.name for f in fields(ControlMessage)],
                         [f.name for f in fields(self.eye_types.ControlMessage)])
        self.assertEqual(get_type_hints(ControlMessage), get_type_hints(self.eye_types.ControlMessage))

    def test_window_requires_a_double_buffered_gles_context(self) -> None:
        pyglet = self.renderer_module.pyglet
        display = MagicMock()
        window = MagicMock()
        with patch.object(pyglet, "display", display, create=True), \
             patch.object(pyglet, "window", window, create=True), \
             patch.object(pyglet, "text", MagicMock(), create=True), \
             patch.object(pyglet, "clock", MagicMock(), create=True), \
             patch.object(self.renderer_module.gl, "Config") as config, \
             patch.object(self.renderer_module.EyeRenderer, "init_geometry"), \
             patch.object(self.renderer_module.EyeRenderer, "reload_shaders"), \
             patch("builtins.print"):
            self.renderer_module.EyeRenderer()
        config.assert_called_once_with(opengl_api="gles", major_version=3, minor_version=1, double_buffer=True)
        window.Window.assert_called_once()

    def test_published_json_round_trips_into_pi_renderer(self) -> None:
        publisher = self.publisher_class.__new__(self.publisher_class)
        publisher.socket = MagicMock()
        publisher.send({4: self.message})
        payload = json.loads(publisher.socket.send_string.call_args.args[0])["4"]
        received = self.eye_types.ControlMessage(**payload)
        self.renderer.apply_control_message(received)
        self.assertEqual(asdict(received), payload)
        self.assertEqual(self.renderer.radius, 0.9)
        self.assertEqual(self.renderer.rotation_deg, 13)
        self.assertEqual(self.renderer.eye_lid_position, 0.65)
        self.assertEqual(self.renderer.iris_size, 0.4)
        self.assertEqual(self.renderer.pupil_size, 0.7)
        self.assertEqual(self.renderer.curvature, 0.3)
        self.assertEqual(self.renderer.vein_count, 17)
        self.assertEqual(self.renderer.vein_seed, 4)
        self.assertTrue(self.renderer.is_cat_eye)
        for name in ("iris_color", "iris_accent_color", "iris_center_color", "striation_color",
                     "pupil_color", "sclera_color", "vein_color"):
            self.assertEqual(getattr(self.renderer, name),
                             tuple(c / 255 for c in getattr(self.state, name).as_rgb()))
        self.assertEqual(received.yaw, -12)
        self.assertEqual(received.pitch, 18)

    def test_normalized_controls_clamp_and_zero_veins_is_preserved(self) -> None:
        for method in ("set_iris_size", "set_pupil_size", "set_curvature", "set_eye_lid_position"):
            name = method.removeprefix("set_")
            getattr(self.renderer, method)(-1)
            self.assertEqual(getattr(self.renderer, name), 0)
            getattr(self.renderer, method)(2)
            self.assertEqual(getattr(self.renderer, name), 1)
        self.renderer.set_vein_count(0)
        self.assertEqual(self.renderer.vein_count, 0)
        self.renderer.set_vein_count(100)
        self.assertEqual(self.renderer.vein_count, 24)
        self.renderer.set_sclera_color_rgb255((-1, 128, 256))
        self.assertEqual(self.renderer.sclera_color, (0, 128 / 255, 1))

    def test_draw_binds_every_appearance_uniform(self) -> None:
        self.renderer.apply_control_message(self.message)
        self.renderer.window = MagicMock(width=800, height=800)
        self.renderer.pending_text = ""
        self.renderer._start_time = 0
        self.renderer._vao = 1
        self.renderer._program = MagicMock()
        self.renderer._on_draw()
        uniforms = dict(call.args for call in self.renderer._program.__setitem__.call_args_list)
        self.assertEqual(uniforms["radius"], 0.9)
        self.assertEqual(uniforms["curved"], 0.3)
        self.assertEqual(uniforms["numVeins"], 17.0)
        self.assertEqual(uniforms["veinSeed"], 4.0)
        for name in ("irisColor", "irisAccentColor", "irisCenterColor", "striationColor",
                     "pupilColor", "scleraColor", "veinColor", "irisSize", "pupilSize",
                     "eyeLidPosition", "isCatEye", "rotation", "iResolution", "iTime"):
            self.assertIn(name, uniforms)

    def test_shader_reload_keeps_the_working_program_on_failure(self) -> None:
        previous = self.renderer._program = MagicMock()
        self.renderer.build_program = MagicMock(side_effect=RuntimeError("compile failed"))
        with patch("builtins.print"):
            self.renderer.reload_shaders()
        self.assertIs(self.renderer._program, previous)
        previous.delete.assert_not_called()

    def test_shader_reload_rebinds_geometry_and_releases_previous_program(self) -> None:
        previous = self.renderer._program = MagicMock()
        replacement = MagicMock()
        self.renderer.build_program = MagicMock(return_value=replacement)
        self.renderer.bind_geometry_to_program = MagicMock()
        with patch("builtins.print"):
            self.renderer.reload_shaders()
        self.assertIs(self.renderer._program, replacement)
        self.renderer.bind_geometry_to_program.assert_called_once_with(replacement)
        previous.delete.assert_called_once()

    def test_status_and_error_text_override_eye_drawing(self) -> None:
        self.renderer.window = MagicMock(width=800, height=800)
        self.renderer.text_label = MagicMock()
        self.renderer._program = MagicMock()
        for text_type, color in ((self.renderer_module.TextType.INFO, (225, 225, 225, 255)),
                                 (self.renderer_module.TextType.ERROR, (255, 80, 80, 255))):
            self.renderer.set_text(text_type, "Status message")
            self.renderer._on_draw()
            self.assertEqual(self.renderer.text_label.color, color)
            self.assertEqual(self.renderer.text_label.text, "Status message")
        self.assertEqual(self.renderer.text_label.draw.call_count, 2)
        self.renderer._program.use.assert_not_called()


if __name__ == "__main__":
    unittest.main()
