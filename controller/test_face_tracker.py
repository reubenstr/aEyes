from __future__ import annotations

import unittest

from data_types import Detection, Position3D
from face_tracker import FaceTracker, TrackStatus


class FaceTrackerConfirmationTests(unittest.TestCase):
    @staticmethod
    def _detection(x: float, y: float = 0.0, z: float = 0.0) -> Detection:
        return Detection(Position3D(x=x, y=y, z=z))

    @staticmethod
    def _tracker(
        *,
        min_hits: int = 2,
        reacquire_hits: int = 3,
        max_missing_confirmed: int = 1,
    ) -> FaceTracker:
        tracker = FaceTracker()
        tracker.min_hits_to_confirm = min_hits
        tracker.min_hits_to_confirm_reacquiring_tracks = reacquire_hits
        tracker.max_missing_confirmed = max_missing_confirmed
        tracker.max_missing_tentative = 1
        tracker.reid_window_frames = 10
        tracker.reid_max_distance = 1.0
        tracker.base_max_distance = 1.0
        tracker.depth_scale_factor = 0.0
        return tracker

    def _confirm_track(self, tracker: FaceTracker) -> None:
        self.assertEqual(tracker.update([self._detection(1.0)]), {})
        output = tracker.update([self._detection(1.0)])
        self.assertIn(0, output)
        self.assertEqual(tracker.tracks[0].status, TrackStatus.CONFIRMED)

    def _move_confirmed_track_to_lost(self, tracker: FaceTracker) -> None:
        tracker.update([])
        output = tracker.update([])
        self.assertEqual(output, {})
        self.assertEqual(tracker.tracks, {})
        self.assertEqual(len(tracker.lost_tracks), 1)

    def test_new_tracks_use_min_hits_to_confirm(self) -> None:
        tracker = self._tracker(min_hits=3)

        self.assertEqual(tracker.update([self._detection(1.0)]), {})
        self.assertEqual(tracker.update([self._detection(1.0)]), {})
        output = tracker.update([self._detection(1.0)])

        self.assertIn(0, output)
        self.assertEqual(tracker.tracks[0].status, TrackStatus.CONFIRMED)

    def test_lost_reid_uses_reacquiring_confirmation_threshold(self) -> None:
        tracker = self._tracker(min_hits=2, reacquire_hits=3)
        self._confirm_track(tracker)
        self._move_confirmed_track_to_lost(tracker)

        self.assertEqual(tracker.update([self._detection(1.0)]), {})
        self.assertEqual(tracker.tracks[0].status, TrackStatus.REACQUIRING)
        self.assertTrue(tracker.tracks[0].reacquire_from_lost)

        self.assertEqual(tracker.update([self._detection(1.0)]), {})
        output = tracker.update([self._detection(1.0)])

        self.assertIn(0, output)
        self.assertEqual(tracker.tracks[0].status, TrackStatus.CONFIRMED)

    def test_active_reacquisition_holds_previous_output_position(self) -> None:
        tracker = self._tracker(
            min_hits=2,
            reacquire_hits=3,
            max_missing_confirmed=10,
        )
        self._confirm_track(tracker)

        held_position = tracker.update([])[0].position
        output = tracker.update([self._detection(1.2)])

        self.assertIn(0, output)
        self.assertEqual(tracker.tracks[0].status, TrackStatus.REACQUIRING)
        self.assertFalse(tracker.tracks[0].reacquire_from_lost)
        self.assertAlmostEqual(float(output[0].position.x), float(held_position.x))

    def test_one_frame_errant_reacquisition_does_not_move_public_track(self) -> None:
        tracker = self._tracker(
            min_hits=2,
            reacquire_hits=3,
            max_missing_confirmed=10,
        )
        self._confirm_track(tracker)

        held_position = tracker.update([])[0].position
        tracker.update([self._detection(1.2)])
        output = tracker.update([])

        self.assertIn(0, output)
        self.assertEqual(tracker.tracks[0].status, TrackStatus.CONFIRMED)
        self.assertAlmostEqual(float(output[0].position.x), float(held_position.x))
        self.assertIsNone(tracker.tracks[0].reacquire_kalman)


if __name__ == "__main__":
    unittest.main()
