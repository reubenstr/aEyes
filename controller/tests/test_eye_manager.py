from __future__ import annotations

import math
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from colors import BLACK, GREY
from conversions import Conversions
from data_types import CameraConfig, Color, EyeConfig, Position3D, TrackedFace
from eye_manager import EyeManager
from parameters import _validate, params


class EyeManagerRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 10.0
        clock = patch("eye_manager.time.monotonic", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        settings = patch.object(params, "eye_manager", replace(params.eye_manager))
        settings.start()
        self.addCleanup(settings.stop)
        self.configs = [EyeConfig(1), EyeConfig(2, Position3D(0.0, 1.0, 0.0))]
        self.manager = EyeManager(self.configs, CameraConfig())
        self.assignments = {1: 7, 2: None}
        self.manager._eye_assigner.update = Mock(side_effect=lambda _: self.assignments.copy())

    def step(self, distance: float | None, dt: float):
        self.now += dt
        faces = {} if distance is None else {7: TrackedFace(Position3D(distance, 0.0, 0.0))}
        return self.manager.update(faces)

    def test_distance_endpoints_and_midpoint(self) -> None:
        for distance, expected in ((0, 1.0), (0.5, 1.0), (1.75, 0.75), (3, 0.5), (100, 0.5)):
            with self.subTest(distance=distance):
                self.assertAlmostEqual(self.manager._resting_openness_for_distance(distance), expected)
        openings = [self.manager._resting_openness_for_distance(i / 10) for i in range(40)]
        self.assertEqual(openings, sorted(openings, reverse=True))

    def test_distance_and_openness_endpoints_are_configurable(self) -> None:
        p = params.eye_manager
        p.eyelid_near_distance_m = 1.0
        p.eyelid_far_distance_m = 5.0
        p.eyelid_near_openness = 0.9
        p.eyelid_far_openness = 0.3
        self.assertAlmostEqual(self.manager._resting_openness_for_distance(3.0), 0.6)

    def test_distance_uses_camera_and_individual_eye_offsets(self) -> None:
        conversions = Conversions(
            [EyeConfig(1, Position3D(1, 2, 3)), EyeConfig(2, Position3D(2, 0, 0))],
            CameraConfig(4, 5, 6),
        )
        target = Position3D(1, 1, 1)
        self.assertAlmostEqual(conversions.get_target_distance(1, target), math.sqrt(48))
        self.assertAlmostEqual(conversions.get_target_distance(2, target), math.sqrt(94))

    def test_smoothing_is_independent_of_update_rate(self) -> None:
        target = {7: TrackedFace(Position3D(0.5, 0.0, 0.0))}
        state = self.manager._states[1]
        state.face_id = 7
        results = []
        for steps in (1, 15, 60):
            state.resting_eye_lid = 0.85
            for _ in range(steps):
                self.manager._update_resting_eyelids(target, 1 / steps)
            results.append(state.resting_eye_lid)
        for result in results:
            self.assertAlmostEqual(result, 1.0 - 0.15 * math.exp(-6.0), places=12)

    def test_update_smooths_rest_and_colors_using_the_same_dt(self) -> None:
        state = self.step(0.5, 0.25)[1]
        self.assertAlmostEqual(state.resting_eye_lid, 1.0 - 0.15 * math.exp(-1.5))
        self.assertNotEqual(state.iris_color, GREY)
        self.assertEqual(self.manager._last_update, self.now)

    def test_all_palette_channels_are_independent_of_update_rate(self) -> None:
        results = []
        for steps in (1, 15, 60):
            manager = EyeManager(self.configs, CameraConfig())
            state = manager._states[1]
            state.face_id = 7
            manager._set_palette(state, Color(12, 34, 56))
            for _ in range(steps):
                manager._lerp_colors(1 / steps)
            results.append([getattr(state, name) for name in manager._palette_channels])
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0], results[2])

    def test_blink_closes_completely_and_returns_to_distance_rest(self) -> None:
        self.step(3.0, 0.1)
        closed = self.step(3.0, 0.5)[1]
        self.assertEqual(closed.eye_lid, 0.0)
        self.assertGreater(closed.resting_eye_lid, 0.5)
        reopened = self.step(3.0, 0.5)[1]
        self.assertAlmostEqual(reopened.eye_lid, reopened.resting_eye_lid)
        self.assertLess(reopened.eye_lid, 0.51)
        self.assertIsNone(self.manager._blink_starts[1])

    def test_distance_changes_during_blink_do_not_cancel_closure(self) -> None:
        self.step(3.0, 0.1)
        self.assertEqual(self.step(0.5, 0.5)[1].eye_lid, 0.0)
        reopened = self.step(0.5, 0.5)[1]
        self.assertAlmostEqual(reopened.eye_lid, reopened.resting_eye_lid)
        self.assertGreater(reopened.eye_lid, 0.99)

    def test_blink_publishes_a_fully_closed_frame_at_15_hz(self) -> None:
        openness = [self.step(3.0, 1 / 15)[1].eye_lid for _ in range(18)]
        self.assertIn(0.0, openness)
        self.assertIsNone(self.manager._blink_starts[1])
        self.assertAlmostEqual(openness[-1], self.manager._states[1].resting_eye_lid)

    def test_target_loss_smoothly_returns_to_neutral_palette_and_opening(self) -> None:
        self.step(0.5, 2.0)
        self.step(0.5, 1.0)
        previous_rest = self.manager._states[1].resting_eye_lid
        self.assignments[1] = None
        lost = self.step(None, 0.1)[1]
        self.assertGreater(lost.resting_eye_lid, 0.85)
        self.assertLess(lost.resting_eye_lid, previous_rest)
        self.assertEqual(lost.eye_lid, lost.resting_eye_lid)
        self.assertEqual(lost.target_iris_color, GREY)
        self.assertEqual(lost.target_iris_accent_color, GREY)
        self.assertEqual(lost.target_iris_center_color, GREY)
        self.assertEqual(lost.target_striation_color, BLACK)
        neutral = self.step(None, 2.0)[1]
        self.assertEqual(neutral.iris_color, GREY)
        self.assertEqual(neutral.iris_accent_color, GREY)
        self.assertEqual(neutral.iris_center_color, GREY)
        self.assertEqual(neutral.striation_color, BLACK)

    def test_reassignment_restarts_blink_and_uses_new_target_distance(self) -> None:
        self.step(3.0, 0.1)
        self.step(3.0, 1.0)
        self.assignments[1] = 8
        self.now += 0.1
        state = self.manager.update({8: TrackedFace(Position3D(0.5, 0.0, 0.0))})[1]
        self.assertEqual(state.face_id, 8)
        self.assertEqual(self.manager._blink_starts[1], self.now)
        self.assertGreater(state.resting_eye_lid, 0.5)

    def test_eyes_share_face_palette_and_have_stable_individual_veins(self) -> None:
        self.assignments[2] = 7
        states = self.step(1.0, 0.1)
        for name in ("target_iris_color", "target_iris_accent_color", "target_iris_center_color", "target_striation_color"):
            self.assertEqual(getattr(states[1], name), getattr(states[2], name))
        self.assertNotEqual(states[1].target_iris_accent_color, states[1].target_iris_center_color)
        self.assertNotEqual(states[1].target_striation_color, BLACK)
        self.assertEqual([s.vein_seed for s in states.values()], [1, 2])
        self.assertEqual(self.step(1.0, 1.0)[1].vein_seed, 1)

    def test_static_settings_are_loaded_from_controller_config(self) -> None:
        params.eye_manager.vein_count = 0
        params.eye_manager.vein_seed = 42
        params.eye_manager.sclera_color = (10, 20, 30)
        manager = EyeManager(self.configs, CameraConfig())
        for state in manager.update({}).values():
            self.assertEqual(state.vein_count, 0)
            self.assertEqual(state.vein_seed, 42)
            self.assertEqual(state.sclera_color, Color(10, 20, 30))
            self.assertEqual(state.eye_lid, 0.85)

    def test_invalid_appearance_and_eyelid_config_is_rejected(self) -> None:
        for name, value in (
            ("vein_count", -1), ("vein_count", 25), ("vein_count", 1.5),
            ("vein_seed", 1.5), ("pupil_size", 1.1), ("curvature", float("nan")),
            ("radius", 0), ("sclera_color", [256, 0, 0]),
            ("eyelid_near_distance_m", 3.0), ("eyelid_far_distance_m", float("inf")),
            ("eyelid_near_openness", 0.4), ("eyelid_smoothing_rate", 0),
        ):
            with self.subTest(name=name, value=value), patch.object(params.eye_manager, name, value):
                with self.assertRaises(ValueError):
                    _validate(params)


if __name__ == "__main__":
    unittest.main()
