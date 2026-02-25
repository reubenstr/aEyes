#!/usr/bin/env python3
"""
Headless D435 face detection + XYZ (NO LANDMARKS anywhere)

- FaceDetectorTRTSCRFDBoxesOnly:
    * TensorRT (cuda-python) execution
    * Copies ONLY scores+boxes outputs (skips all keypoints/landmarks outputs)
    * Top-K pruning per feature level before decode + global NMS
    * Returns bboxes in full color image coords

- RealSenseD435XYZ:
    * Streams color+depth at same FPS
    * Aligns depth to color
    * Computes robust Z from bbox ROI and deprojects bbox center to XYZ (meters)

Tuning knobs:
  CONF_THRESH, TOPK_PER_LEVEL, PRINT_EVERY_N_FRAMES

Fixes applied vs. original:
  1. Corrected typo in main(): FaceDetectorTRTSSCRFDBoxesOnly -> clean single assignment.
  2. Fixed D2H sync ordering: cudaStreamSynchronize now runs BEFORE reading host buffers,
     preventing reads of stale/partial data from async memcpy.
  3. Added wait_for_frames() timeout (5 s) to avoid infinite hang on USB hiccup.
  4. Added _intr None guard in face_xyz() to prevent crash before first valid frame.
"""

from __future__ import annotations

import time
import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import cv2
import pyrealsense2 as rs
import tensorrt as trt
from cuda import cudart


# ---------------------- User settings ----------------------
ENGINE_PATH = "face_480_fp16.engine"

INPUT_W = 480
INPUT_H = 480

RS_W = 640
RS_H = 480
RS_FPS = 60

CONF_THRESH = 0.55
NMS_IOU_THRESH = 0.4
TOPK_PER_LEVEL = 400
STRIDES = (8, 16, 32)

ROI_INNER_FRAC = 0.4
Z_MIN_M = 0.2
Z_MAX_M = 10.0

PRINT_EVERY_N_FRAMES = 30
PRINT_TOP_K = 3

RS_FRAME_TIMEOUT_MS = 5000
# ----------------------------------------------------------


TRT_LOGGER = trt.Logger(trt.Logger.WARNING)


@dataclass
class FaceDetection:
    score: float
    bbox_xyxy: np.ndarray  # shape (4,) float32 in full color coords (640x480)


class FaceDetectorTRTSCRFDBoxesOnly:
    """
    SCRFD-style TensorRT engine runner (boxes only).
    Uses output bindings (scores, boxes) for 3 levels: (1,2), (4,5), (7,8).
    """

    def __init__(
        self,
        engine_path: str,
        input_w: int,
        input_h: int,
        conf_thresh: float,
        nms_iou_thresh: float,
        topk_per_level: int,
        strides: Tuple[int, ...] = (8, 16, 32),
        output_groups: Tuple[Tuple[int, int], ...] = ((1, 2), (4, 5), (7, 8)),
    ):
        self.engine_path = engine_path
        self.input_w = int(input_w)
        self.input_h = int(input_h)
        self.conf_thresh = float(conf_thresh)
        self.nms_iou_thresh = float(nms_iou_thresh)
        self.topk_per_level = int(topk_per_level)
        self.strides = strides
        self.output_groups = output_groups

        self.engine = self._load_engine(engine_path)
        self.context = self.engine.create_execution_context()
        if self.context is None:
            raise RuntimeError("Failed to create TensorRT execution context.")

        self.bindings, self._bufs, self.stream, self._by_index = self._allocate_io()

        # Input assumed at binding 0
        self._in_host = self._by_index[0]["host"]
        self._in_dptr = self._by_index[0]["dptr"]
        self._in_nbytes = self._by_index[0]["nbytes"]

    def close(self):
        self._free_io()

    # ---------------- CUDA / TRT plumbing ----------------

    @staticmethod
    def _check_cuda(ret):
        if not isinstance(ret, tuple):
            if ret != cudart.cudaError_t.cudaSuccess:
                raise RuntimeError(f"CUDA error: {ret}")
            return None
        if len(ret) == 0:
            raise RuntimeError("CUDA call returned empty tuple.")
        err = ret[0]
        if err != cudart.cudaError_t.cudaSuccess:
            raise RuntimeError(f"CUDA error: {err}")
        if len(ret) == 1:
            return None
        if len(ret) == 2:
            return ret[1]
        return ret[1:]

    def _load_engine(self, path: str) -> trt.ICudaEngine:
        with open(path, "rb") as f, trt.Runtime(TRT_LOGGER) as rt:
            e = rt.deserialize_cuda_engine(f.read())
        if e is None:
            raise RuntimeError(f"Failed to load engine: {path}")
        return e

    def _allocate_io(self):
        stream = self._check_cuda(cudart.cudaStreamCreate())

        in_idx = [
            i
            for i in range(self.engine.num_bindings)
            if self.engine.binding_is_input(i)
        ][0]
        self.context.set_binding_shape(in_idx, (1, 3, self.input_h, self.input_w))

        bindings = [0] * self.engine.num_bindings
        bufs = []
        by_index = {}

        for i in range(self.engine.num_bindings):
            name = self.engine.get_binding_name(i)
            dtype = trt.nptype(self.engine.get_binding_dtype(i))
            shape = tuple(self.context.get_binding_shape(i))

            n = int(np.prod(shape))
            nbytes = n * np.dtype(dtype).itemsize
            if nbytes <= 0:
                raise RuntimeError(
                    f"Invalid binding size for {i} {name}: shape={shape}"
                )

            host = np.empty(n, dtype=dtype)
            dptr = self._check_cuda(cudart.cudaMalloc(nbytes))

            bindings[i] = int(dptr)
            rec = {
                "index": i,
                "name": name,
                "dtype": dtype,
                "shape": shape,
                "nbytes": nbytes,
                "host": host,
                "dptr": dptr,
                "is_input": self.engine.binding_is_input(i),
            }
            bufs.append(rec)
            by_index[i] = rec

        return bindings, bufs, stream, by_index

    def _free_io(self):
        for rec in getattr(self, "_bufs", []):
            try:
                self._check_cuda(cudart.cudaFree(rec["dptr"]))
            except Exception:
                pass
        try:
            self._check_cuda(cudart.cudaStreamDestroy(self.stream))
        except Exception:
            pass

    # ---------------- Preprocess ----------------

    def _preprocess_center_crop(self, frame_bgr: np.ndarray):
        """
        Center-crop to (input_w, input_h), then BGR->RGB, normalize [0,1], NCHW float32.
        Returns (inp, x0, y0).
        """
        h, w = frame_bgr.shape[:2]
        if w < self.input_w or h < self.input_h:
            raise ValueError(
                f"Frame too small: {w}x{h} for crop {self.input_w}x{self.input_h}"
            )

        x0 = (w - self.input_w) // 2
        y0 = (h - self.input_h) // 2
        roi = frame_bgr[y0 : y0 + self.input_h, x0 : x0 + self.input_w]

        rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
        x = rgb.astype(np.float32) * (1.0 / 255.0)
        x = np.transpose(x, (2, 0, 1))  # CHW
        x = np.expand_dims(x, axis=0)  # NCHW
        return np.ascontiguousarray(x), x0, y0

    # ---------------- Decode + NMS (boxes only) ----------------

    @staticmethod
    def _iou_one_to_many(box, boxes):
        x1 = np.maximum(box[0], boxes[:, 0])
        y1 = np.maximum(box[1], boxes[:, 1])
        x2 = np.minimum(box[2], boxes[:, 2])
        y2 = np.minimum(box[3], boxes[:, 3])
        inter = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
        area_a = (box[2] - box[0]) * (box[3] - box[1])
        area_b = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
        return inter / (area_a + area_b - inter + 1e-9)

    def _nms(self, boxes, scores):
        if boxes.shape[0] == 0:
            return np.array([], dtype=np.int64)
        order = scores.argsort()[::-1]
        keep = []
        while order.size > 0:
            i = order[0]
            keep.append(i)
            if order.size == 1:
                break
            rest = order[1:]
            ious = self._iou_one_to_many(boxes[i], boxes[rest])
            order = rest[ious < self.nms_iou_thresh]
        return np.array(keep, dtype=np.int64)

    def _infer_stride(self, N: int):
        for s in self.strides:
            fh, fw = self.input_h // s, self.input_w // s
            loc = fh * fw
            if loc > 0 and (N % loc == 0):
                A = N // loc
                if A in (1, 2, 4, 6):
                    return s, fh, fw, A
        raise RuntimeError(
            f"Could not infer stride for N={N} at {self.input_w}x{self.input_h}"
        )

    @staticmethod
    def _make_centers(fh, fw, stride, A):
        xs = (np.arange(fw) + 0.5) * stride
        ys = (np.arange(fh) + 0.5) * stride
        xv, yv = np.meshgrid(xs, ys)
        centers = np.stack([xv.reshape(-1), yv.reshape(-1)], axis=1)
        if A > 1:
            centers = np.repeat(centers, A, axis=0)
        return centers.astype(np.float32)

    @staticmethod
    def _distance2bbox(points, distances):
        x1 = points[:, 0] - distances[:, 0]
        y1 = points[:, 1] - distances[:, 1]
        x2 = points[:, 0] + distances[:, 2]
        y2 = points[:, 1] + distances[:, 3]
        return np.stack([x1, y1, x2, y2], axis=1)

    def _decode_level_topk(self, scores_2d: np.ndarray, boxes_2d: np.ndarray):
        scores = scores_2d.reshape(-1)  # (N,)
        N = scores.shape[0]
        if N == 0:
            return np.zeros((0, 4), np.float32), np.zeros((0,), np.float32)

        above = np.where(scores >= self.conf_thresh)[0]
        if above.size == 0:
            return np.zeros((0, 4), np.float32), np.zeros((0,), np.float32)

        if above.size > self.topk_per_level:
            sub_scores = scores[above]
            k = self.topk_per_level
            topk_idx = np.argpartition(sub_scores, -k)[-k:]
            idx = above[topk_idx]
        else:
            idx = above

        stride, fh, fw, A = self._infer_stride(N)
        centers = self._make_centers(fh, fw, stride, A)

        sel_centers = centers[idx]
        sel_boxes = boxes_2d[idx] * stride
        decoded = self._distance2bbox(sel_centers, sel_boxes)
        sel_scores = scores[idx].astype(np.float32, copy=False)

        return decoded.astype(np.float32, copy=False), sel_scores

    def _decode_all(self, level_outputs):
        all_boxes = []
        all_scores = []
        for sc, bx in level_outputs:
            b, s = self._decode_level_topk(sc, bx)
            if b.shape[0]:
                all_boxes.append(b)
                all_scores.append(s)

        if not all_boxes:
            return np.zeros((0, 4), np.float32), np.zeros((0,), np.float32)

        boxes = np.concatenate(all_boxes, axis=0).astype(np.float32, copy=False)
        scores = np.concatenate(all_scores, axis=0).astype(np.float32, copy=False)

        boxes[:, 0] = np.clip(boxes[:, 0], 0, self.input_w - 1)
        boxes[:, 2] = np.clip(boxes[:, 2], 0, self.input_w - 1)
        boxes[:, 1] = np.clip(boxes[:, 1], 0, self.input_h - 1)
        boxes[:, 3] = np.clip(boxes[:, 3], 0, self.input_h - 1)

        keep = self._nms(boxes, scores)
        return boxes[keep], scores[keep]

    # ---------------- Public API ----------------

    def detect(self, frame_bgr: np.ndarray) -> List[FaceDetection]:
        inp, x0, y0 = self._preprocess_center_crop(frame_bgr)
        np.copyto(self._in_host.reshape(-1), inp.reshape(-1))

        # H2D input
        self._check_cuda(
            cudart.cudaMemcpyAsync(
                self._in_dptr,
                self._in_host,
                self._in_nbytes,
                cudart.cudaMemcpyKind.cudaMemcpyHostToDevice,
                self.stream,
            )
        )

        ok = self.context.execute_async_v2(
            bindings=self.bindings, stream_handle=self.stream
        )
        if not ok:
            raise RuntimeError("execute_async_v2 returned False")

        # D2H ONLY scores+boxes (skip keypoints bindings)
        for si, bi in self.output_groups:
            sc = self._by_index[si]
            bx = self._by_index[bi]

            self._check_cuda(
                cudart.cudaMemcpyAsync(
                    sc["host"],
                    sc["dptr"],
                    sc["nbytes"],
                    cudart.cudaMemcpyKind.cudaMemcpyDeviceToHost,
                    self.stream,
                )
            )
            self._check_cuda(
                cudart.cudaMemcpyAsync(
                    bx["host"],
                    bx["dptr"],
                    bx["nbytes"],
                    cudart.cudaMemcpyKind.cudaMemcpyDeviceToHost,
                    self.stream,
                )
            )

        self._check_cuda(cudart.cudaStreamSynchronize(self.stream))

        # Build level output views only after the stream has been fully flushed.
        level_outputs = []
        for si, bi in self.output_groups:
            sc = self._by_index[si]
            bx = self._by_index[bi]
            sc_view = sc["host"].reshape(sc["shape"])
            bx_view = bx["host"].reshape(bx["shape"])
            level_outputs.append((sc_view, bx_view))

        boxes_crop, scores = self._decode_all(level_outputs)

        dets: List[FaceDetection] = []
        for i in range(boxes_crop.shape[0]):
            b = boxes_crop[i].copy()
            b[[0, 2]] += x0
            b[[1, 3]] += y0
            dets.append(FaceDetection(score=float(scores[i]), bbox_xyxy=b))
        return dets


class RealSenseD435XYZ:
    """
    D435 capture (color+depth same fps), depth aligned to color, compute XYZ for bbox.
    """

    def __init__(
        self,
        w: int,
        h: int,
        fps: int,
        roi_inner_frac: float,
        z_min_m: float,
        z_max_m: float,
    ):
        self.w = int(w)
        self.h = int(h)
        self.fps = int(fps)
        self.roi_inner_frac = float(roi_inner_frac)
        self.z_min_m = float(z_min_m)
        self.z_max_m = float(z_max_m)

        self.pipeline = rs.pipeline()
        cfg = rs.config()
        cfg.enable_stream(rs.stream.color, self.w, self.h, rs.format.bgr8, self.fps)
        cfg.enable_stream(rs.stream.depth, self.w, self.h, rs.format.z16, self.fps)
        self.profile = self.pipeline.start(cfg)

        self.align = rs.align(rs.stream.color)

        depth_sensor = self.profile.get_device().first_depth_sensor()
        self.depth_scale = depth_sensor.get_depth_scale()

        # Warm up
        for _ in range(10):
            self.pipeline.wait_for_frames(timeout_ms=RS_FRAME_TIMEOUT_MS)

        self._intr: Optional[rs.intrinsics] = None

    def close(self):
        self.pipeline.stop()

    def get_aligned_frames(self):
        try:
            frames = self.pipeline.wait_for_frames(timeout_ms=RS_FRAME_TIMEOUT_MS)
        except RuntimeError as exc:
            # wait_for_frames raises RuntimeError on timeout.
            print(f"[WARN] wait_for_frames timed out or failed: {exc}")
            return None, None, None

        frames = self.align.process(frames)
        color_frame = frames.get_color_frame()
        depth_frame = frames.get_depth_frame()
        if not color_frame or not depth_frame:
            return None, None, None

        color = np.asanyarray(color_frame.get_data())
        depth = np.asanyarray(depth_frame.get_data())

        if self._intr is None:
            self._intr = color_frame.profile.as_video_stream_profile().intrinsics

        return color, depth, self._intr

    def _robust_z_m(
        self, depth_u16: np.ndarray, bbox_xyxy: np.ndarray
    ) -> Optional[float]:
        x1, y1, x2, y2 = [int(v) for v in bbox_xyxy]
        h, w = depth_u16.shape[:2]

        x1 = max(0, min(w - 1, x1))
        x2 = max(0, min(w, x2))
        y1 = max(0, min(h - 1, y1))
        y2 = max(0, min(h, y2))
        if x2 <= x1 or y2 <= y1:
            return None

        bw = x2 - x1
        bh = y2 - y1
        inner_w = max(2, int(bw * self.roi_inner_frac))
        inner_h = max(2, int(bh * self.roi_inner_frac))
        cx = x1 + bw // 2
        cy = y1 + bh // 2

        ix1 = max(0, cx - inner_w // 2)
        ix2 = min(w, cx + inner_w // 2)
        iy1 = max(0, cy - inner_h // 2)
        iy2 = min(h, cy + inner_h // 2)

        roi = depth_u16[iy1:iy2, ix1:ix2].reshape(-1)
        if roi.size == 0:
            return None
        roi = roi[roi > 0]
        if roi.size == 0:
            return None

        z = roi.astype(np.float32) * self.depth_scale
        z = z[(z >= self.z_min_m) & (z <= self.z_max_m)]
        if z.size == 0:
            return None

        return float(np.median(z))

    @staticmethod
    def _deproject(intr: rs.intrinsics, u: int, v: int, z_m: float):
        X, Y, Z = rs.rs2_deproject_pixel_to_point(
            intr, [float(u), float(v)], float(z_m)
        )
        return float(X), float(Y), float(Z)

    def face_xyz(
        self,
        depth_u16: np.ndarray,
        intr: Optional[rs.intrinsics],
        bbox_xyxy: np.ndarray,
    ) -> Optional[Tuple[float, float, float]]:

        if intr is None:
            return None

        z_m = self._robust_z_m(depth_u16, bbox_xyxy)
        if z_m is None:
            return None

        x1, y1, x2, y2 = bbox_xyxy
        u = int((x1 + x2) * 0.5)
        v = int((y1 + y2) * 0.5)
        return self._deproject(intr, u, v, z_m)


class Detector:
    def __init__(self):
        self.cam = RealSenseD435XYZ(
            w=RS_W,
            h=RS_H,
            fps=RS_FPS,
            roi_inner_frac=ROI_INNER_FRAC,
            z_min_m=Z_MIN_M,
            z_max_m=Z_MAX_M,
        )

        self.det = FaceDetectorTRTSCRFDBoxesOnly(
            engine_path=ENGINE_PATH,
            input_w=INPUT_W,
            input_h=INPUT_H,
            conf_thresh=CONF_THRESH,
            nms_iou_thresh=NMS_IOU_THRESH,
            topk_per_level=TOPK_PER_LEVEL,
            strides=STRIDES,
            output_groups=((1, 2), (4, 5), (7, 8)),
        )

    def get_closest_point(self) -> Optional[Tuple[float, float, float]]:
        color_bgr, depth_u16, intr = self.cam.get_aligned_frames()
        if color_bgr is None:
            return None

        faces = self.det.detect(color_bgr)

        closest_point = None
        min_dist = float("inf")

        for f in faces:
            xyz = self.cam.face_xyz(depth_u16, intr, f.bbox_xyxy)
            if xyz is None:
                continue

            # If it's a single point (x, y, z)
            if isinstance(xyz[0], (int, float)):
                points = [xyz]
            else:
                points = xyz

            for x, y, z in points:
                if not all(map(math.isfinite, (x, y, z))):
                    continue

                dist = math.sqrt(x*x + y*y + z*z)

                if dist < min_dist:
                    min_dist = dist
                    closest_point = (x, y, z)

        return closest_point
 

    def shutdown(self):
        self.det.close()
        self.cam.close()


'''
def main():
    cam = RealSenseD435XYZ(
        w=RS_W,
        h=RS_H,
        fps=RS_FPS,
        roi_inner_frac=ROI_INNER_FRAC,
        z_min_m=Z_MIN_M,
        z_max_m=Z_MAX_M,
    )

    det = FaceDetectorTRTSCRFDBoxesOnly(
        engine_path=ENGINE_PATH,
        input_w=INPUT_W,
        input_h=INPUT_H,
        conf_thresh=CONF_THRESH,
        nms_iou_thresh=NMS_IOU_THRESH,
        topk_per_level=TOPK_PER_LEVEL,
        strides=STRIDES,
        output_groups=((1, 2), (4, 5), (7, 8)),
    )

    frame_count = 0
    last_t = time.time()
    fps_ema = None

    try:
        while True:
            color_bgr, depth_u16, intr = cam.get_aligned_frames()
            if color_bgr is None:
                continue

            faces = det.detect(color_bgr)

            out = []
            for f in faces:
                xyz = cam.face_xyz(depth_u16, intr, f.bbox_xyxy)
                if xyz is not None:
                    out.append((f, xyz))
                    print((f, xyz))

            now = time.time()
            fps = 1.0 / max(1e-6, now - last_t)
            last_t = now
            fps_ema = fps if fps_ema is None else (0.9 * fps_ema + 0.1 * fps)

            frame_count += 1
            if frame_count % PRINT_EVERY_N_FRAMES == 0:
                print(f"FPS(EMA): {fps_ema:.1f}  faces_with_xyz: {len(out)}")
                for i in range(min(PRINT_TOP_K, len(out))):
                    f, (X, Y, Z) = out[i]
                    x1, y1, x2, y2 = f.bbox_xyxy
                    print(
                        f"  face{i}: score={f.score:.3f} "
                        f"bbox=({x1:.0f},{y1:.0f})-({x2:.0f},{y2:.0f}) "
                        f"XYZ=({X:.3f},{Y:.3f},{Z:.3f}) m"
                    )

    finally:
        det.close()
        cam.close()


if __name__ == "__main__":
    main()
'''