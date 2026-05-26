from __future__ import annotations

import unittest

from config import EYE_CONFIGS
from data_types import Position3D, TrackedFace
from eye_assigner import EyeAssigner


class EyeAssignerProximityTests(unittest.TestCase):
    def test_bottom_right_face_gets_bottom_right_eye(self) -> None:
        assigner = EyeAssigner(EYE_CONFIGS)

        assignments = assigner.update({
            1: TrackedFace(Position3D(x=1.0, y=0.18, z=-0.31177)),
        })

        self.assertEqual(assignments[5], 1)
        self.assertNotEqual(assignments[3], 1)

    def test_bottom_left_face_gets_bottom_left_eye(self) -> None:
        assigner = EyeAssigner(EYE_CONFIGS)

        assignments = assigner.update({
            1: TrackedFace(Position3D(x=1.0, y=-0.18, z=-0.31177)),
        })

        self.assertEqual(assignments[6], 1)
        self.assertNotEqual(assignments[2], 1)

    def test_steal_for_uncovered_face_uses_layout_distance(self) -> None:
        assigner = EyeAssigner(EYE_CONFIGS, assign_interval_s=0.0)
        donor_face = 1
        uncovered_face = 2

        donor = TrackedFace(Position3D(x=1.0, y=0.0, z=0.0))
        first_assignments = assigner.update({donor_face: donor})
        self.assertTrue(
            all(face_id == donor_face for face_id in first_assignments.values())
        )

        assignments = assigner.update({
            donor_face: donor,
            uncovered_face: TrackedFace(Position3D(x=1.0, y=0.18, z=-0.31177)),
        })

        self.assertEqual(assignments[5], uncovered_face)
        self.assertNotEqual(assignments[3], uncovered_face)


if __name__ == "__main__":
    unittest.main()
