from __future__ import annotations

import unittest
from unittest.mock import patch
import numpy as np

from data_types import Detection, Position3D
from face_tracker import FaceTracker, TrackStatus
from kalman_filter_3d import KalmanFilter3D
from parameters import params


def detection(x=2., y=0., z=0., **kwargs):
    return Detection(Position3D(x, y, z), **kwargs)


class FaceTrackerTests(unittest.TestCase):
    def tracker(self, **settings):
        tracker = FaceTracker()
        tracker.min_hits_to_confirm = 1
        for name, value in settings.items():
            setattr(tracker, name, value)
        return tracker

    def test_new_confirmation_requires_actual_observations(self):
        tracker = self.tracker(min_hits_to_confirm=3)
        self.assertEqual(tracker.update([detection()]), {})
        self.assertEqual(tracker.update(None, timestamp=0.09), {})
        self.assertEqual(tracker.update([detection()]), {})
        self.assertIn(0, tracker.update([detection()]))

    def test_one_hit_threshold_confirms_at_spawn(self):
        self.assertIn(0, self.tracker().update([detection()]))

    def test_active_track_resumes_on_first_returning_detection(self):
        tracker = self.tracker()
        tracker.update([detection()])
        previous = tracker.update([])[0].position.y
        result = tracker.update([detection(y=0.15)])
        self.assertEqual(tracker.tracks[0].status, TrackStatus.CONFIRMED)
        self.assertGreater(result[0].position.y, previous)

    def test_outlier_cannot_displace_confirmed_track(self):
        tracker = self.tracker()
        tracker.update([detection()])
        tracker.update([])
        result = tracker.update([detection(y=2.)])
        self.assertAlmostEqual(result[0].position.y, 0.)

    def test_missing_frame_predicts_once_and_coasts_public_output(self):
        tracker = self.tracker()
        tracker.update([detection()], timestamp=1.)
        tracker.tracks[0].kalman.state[4] = 0.3
        output = tracker.update([], timestamp=1.1)
        self.assertAlmostEqual(tracker.tracks[0].kalman.position.y, 0.03)
        self.assertAlmostEqual(output[0].position.y, 0.03)

    def test_absent_frame_does_not_mutate_measurement_state_or_counters(self):
        tracker = self.tracker()
        tracker.update([detection()], timestamp=1.)
        track = tracker.tracks[0]
        track.kalman.state[4] = 0.3
        state, covariance = track.kalman.state.copy(), track.kalman.P.copy()
        output = tracker.update(None, timestamp=1.1)
        np.testing.assert_array_equal(track.kalman.state, state)
        np.testing.assert_array_equal(track.kalman.P, covariance)
        self.assertEqual((track.missing_frames, track.consecutive_hits), (0, 1))
        self.assertAlmostEqual(output[0].position.y, 0.03)
        self.assertEqual(tracker._timestamp, 1.)

    def test_public_prediction_is_bounded_and_camera_silence_expires_output(self):
        tracker = self.tracker()
        tracker.update([detection()], timestamp=1.)
        tracker.tracks[0].kalman.state[4] = 1.
        self.assertAlmostEqual(tracker.get_output(1.5)[0].position.y, params.tracker.coast_time_s)
        self.assertEqual(tracker.get_output(3.1), {})

    def test_lifetime_uses_elapsed_seconds_not_number_of_polls(self):
        for timestamps in ([1.05, 1.1, 1.15], [1.15]):
            tracker = self.tracker(max_missing_confirmed=3)
            tracker.update([detection()], timestamp=1.)
            for timestamp in timestamps:
                self.assertIn(0, tracker.update([], timestamp=timestamp))
            self.assertEqual(tracker.update([], timestamp=1.21), {})
            self.assertEqual(len(tracker.lost_tracks), 1)

    def test_late_or_duplicate_capture_does_not_update_filter(self):
        tracker = self.tracker()
        tracker.update([detection()], timestamp=1.)
        for timestamp in (1., 0.5):
            tracker.update([detection(y=0.2)], timestamp=timestamp)
        self.assertEqual(tracker.tracks[0].hits, 1)
        self.assertEqual(tracker.tracks[0].kalman.position.y, 0.)

    def test_lost_reid_requires_its_own_confirmation(self):
        tracker = self.tracker(max_missing_confirmed=1, min_hits_to_confirm_reacquiring_tracks=3)
        tracker.update([detection()])
        tracker.update([])
        self.assertEqual(tracker.update([]), {})
        self.assertEqual(tracker.update([detection()]), {})
        self.assertEqual(tracker.tracks[0].status, TrackStatus.REACQUIRING)
        self.assertEqual(tracker.update([detection()]), {})
        self.assertIn(0, tracker.update([detection()]))

    def test_tentative_false_positive_is_not_retained_for_reid(self):
        tracker = self.tracker(min_hits_to_confirm=3, max_missing_tentative=1)
        tracker.update([detection()])
        tracker.update([])
        tracker.update([])
        self.assertEqual(tracker.lost_tracks, [])

    def test_lost_filter_continues_prediction(self):
        tracker = self.tracker(max_missing_confirmed=1)
        tracker.update([detection()], timestamp=1.)
        track = tracker.tracks[0]
        track.kalman.state[4] = 0.3
        tracker.update([], timestamp=1.1)
        before = track.kalman.position.y
        tracker.update([], timestamp=1.2)
        self.assertAlmostEqual(track.kalman.position.y - before, 0.03)

    def test_failed_reacquisition_does_not_restart_lost_retention(self):
        tracker = self.tracker(max_missing_confirmed=1, reid_window_frames=5)
        tracker.update([detection()], timestamp=1.)
        tracker.update([], timestamp=1.1)
        lost_at = tracker.lost_tracks[0][0]
        tracker.update([detection()], timestamp=1.15)
        tracker.update([], timestamp=1.2)
        self.assertAlmostEqual(tracker.lost_tracks[0][0], lost_at)
        tracker.update([], timestamp=1.5)
        self.assertEqual(tracker.lost_tracks, [])

    def test_gate_depends_on_forward_depth_not_height(self):
        tracker = self.tracker()
        self.assertAlmostEqual(tracker._adaptive_max_distance(Position3D(5, 0, 0)), 1.)
        self.assertAlmostEqual(tracker._adaptive_max_distance(Position3D(1, 0, 5)), 0.4)

    def test_gated_assignment_preserves_two_feasible_matches(self):
        tracker = self.tracker()
        tracker._spawn_track(detection(y=0.))
        tracker._spawn_track(detection(y=0.3))
        detections = [detection(y=0.1), detection(y=0.074, z=0.342)]
        matches, unmatched_dets, unmatched_tracks = tracker._match(detections, list(tracker.tracks.values()), 0.4)
        self.assertEqual(set(matches), {(0, 1), (1, 0)})
        self.assertEqual((unmatched_dets, unmatched_tracks), ([], []))

    def test_all_impossible_pairs_use_unmatched_options(self):
        tracker = self.tracker()
        tracker._spawn_track(detection())
        self.assertEqual(tracker._match([detection(y=5)], list(tracker.tracks.values())), ([], [0], [0]))

    def test_covariance_gate_rejects_unlikely_innovation(self):
        tracker = self.tracker()
        tracker._spawn_track(detection())
        track = tracker.tracks[0]
        track.kalman.P *= 0.001
        self.assertEqual(tracker._match([detection(y=0.25)], [track])[0], [])
        track.kalman.P[:3, :3] = np.eye(3) * 0.1
        self.assertEqual(tracker._match([detection(y=0.25)], [track])[0], [(0, 0)])

    def test_image_only_association_survives_brief_depth_failure(self):
        tracker = self.tracker()
        bbox = (0.2, 0.2, 0.4, 0.4)
        tracker.update([detection(bbox=bbox)], timestamp=1.)
        result = tracker.update([Detection(None, bbox=(0.21, 0.2, 0.41, 0.4), depth_quality=0.)], timestamp=1.1)
        self.assertIn(0, result)
        self.assertEqual(tracker.tracks[0].last_seen, 1.1)
        self.assertEqual(tracker.tracks[0].last_depth_seen, 1.)
        tracker.update([detection(y=0.1, bbox=bbox)], timestamp=1.2)
        self.assertGreater(tracker.get_output()[0].position.y, 0.)
        self.assertEqual(tracker._next_id, 1)

    def test_image_only_observations_cannot_keep_stale_depth_alive(self):
        tracker = self.tracker()
        bbox = (0.2, 0.2, 0.4, 0.4)
        tracker.update([detection(bbox=bbox)], timestamp=1.)
        for timestamp in (1.1, 1.4, 1.6, 2., 3., 3.5):
            result = tracker.update([Detection(None, bbox=bbox, depth_quality=0.)], timestamp=timestamp)
        self.assertEqual(result, {})
        self.assertEqual(tracker.tracks, {})
        self.assertEqual(tracker._next_id, 1)

    def test_invalid_measurements_do_not_poison_the_filter(self):
        tracker = self.tracker()
        tracker.update([detection()])
        tracker.update([detection(x=float('nan')), detection(confidence=float('nan')),
                        Detection(None, bbox=(0., 0., 0., 1.))])
        self.assertTrue(np.isfinite(tracker.tracks[0].kalman.state).all())
        self.assertEqual(tracker._next_id, 1)

    def test_static_history_resets_on_observed_miss(self):
        with patch.object(params.tracker, 'static_window', 2):
            tracker = self.tracker()
            for _ in range(6):
                tracker.update([detection()])
            self.assertTrue(tracker.tracks[0].is_static)
            tracker.update([])
            self.assertFalse(tracker.tracks[0].is_static)
            self.assertEqual(len(tracker.tracks[0].speed_window), 0)


class KalmanTimingTests(unittest.TestCase):
    def test_depth_noise_is_forward_and_values_are_standard_deviations(self):
        kf = KalmanFilter3D(Position3D(2, 0, 0))
        np.testing.assert_allclose(kf.R.diagonal(), [0.2 ** 2, 0.05 ** 2, 0.05 ** 2])

    def test_prediction_and_covariance_compose_across_irregular_steps(self):
        filters = [KalmanFilter3D(Position3D(2, 0, 0)) for _ in range(2)]
        for kf in filters:
            kf.state[3:] = (0.3, -1., 0.2)
        filters[0].predict(0.5)
        filters[1].predict(0.2)
        filters[1].predict(0.3)
        np.testing.assert_allclose(filters[0].state, filters[1].state, atol=1e-12)
        np.testing.assert_allclose(filters[0].P, filters[1].P, atol=1e-12)

    def test_bad_dt_is_rejected(self):
        for dt in (-1, float('nan')):
            with self.assertRaises(ValueError):
                KalmanFilter3D(Position3D(2, 0, 0)).predict(dt)


if __name__ == '__main__':
    unittest.main()
