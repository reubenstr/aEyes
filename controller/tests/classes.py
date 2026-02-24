#!/usr/bin/env python3
"""
Headless D435 face detection + XYZ using two classes:

- FaceDetectorTRTSCRFD: TensorRT (cuda-python) + SCRFD decode/NMS, returns bboxes (+optional landmarks)
- RealSenseD435XYZ: RealSense color+depth same FPS, depth aligned to color, returns XYZ for a bbox

Assumptions:
- Engine is fixed input (1,3,480,480)
- Outputs grouped by binding index: (1,2,3),(4,5,6),(7,8,9)
"""

from __future__ import annotations

import time
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

CONF_THRESH = 0.5
NMS_IOU_THRESH = 0.4
STRIDES = (8, 16, 32)

ROI_INNER_FRAC = 0.4
Z_MIN_M = 0.2
Z_MAX_M = 10.0

PRINT_EVERY_N_FRAMES = 30
PRINT_TOP_K = 3
# ----------------------------------------------------------


TRT_LOGGER = trt.Logger(trt.Logger.WARNING)


@dataclass
class FaceDetection:
    score: float
    # bbox in full color image coordinates (x1,y1,x2,y2), float32
    bbox_xyxy: np.ndarray  # shape (4,)
    # optional 5-point landmarks (x1,y1,...), full image coords
    kps: Optional[np.ndarray] = None  # shape (10,)


class FaceDetectorTRTSCRFD:
    """
    TensorRT + cuda-python execution + SCRFD decode/NMS.
    Input: BGR image at RS resolution (640x480), center-cropped to 480x480 internally.
    Output: detections in the original full image coordinate system (640x480).
    """

    def __init__(
        self,
        engine_path: str,
        input_w: int,
        input_h: int,
        conf_thresh: float = 0.5,
        nms_iou_thresh: float = 0.4,
        strides: Tuple[int, ...] = (8, 16, 32),
        output_groups: Tuple[Tuple[int, int, int], ...] = ((1, 2, 3), (4, 5, 6), (7, 8, 9)),
    ):
        self.engine_path = engine_path
        self.input_w = input_w
        self.input_h = input_h
        self.conf_thresh = conf_thresh
        self.nms_iou_thresh = nms_iou_thresh
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

    # ---------- TensorRT/CUDA plumbing ----------

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

        # Ensure context sees correct input shape
        in_idx = [i for i in range(self.engine.num_bindings) if self.engine.binding_is_input(i)][0]
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
                raise RuntimeError(f"Invalid binding size for {i} {name}: shape={shape}")

            host = np.empty(n, dtype=dtype)
            dptr = self._check_cuda(cudart.cudaMalloc(nbytes))

            bindings[i] = int(dptr)
            rec = {"index": i, "name": name, "host": host, "dptr": dptr, "shape": shape, "nbytes": nbytes,
                   "is_input": self.engine.binding_is_input(i)}
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

    # ---------- Pre/postprocess ----------

    def _preprocess_center_crop(self, frame_bgr: np.ndarray):
        """
        Center-crop to (input_w,input_h), then BGR->RGB, normalize to [0,1], NCHW.
        Returns (inp, x0, y0).
        """
        h, w = frame_bgr.shape[:2]
        if w < self.input_w or h < self.input_h:
            raise ValueError(f"Frame too small: {w}x{h} for crop {self.input_w}x{self.input_h}")
        x0 = (w - self.input_w) // 2
        y0 = (h - self.input_h) // 2
        roi = frame_bgr[y0:y0 + self.input_h, x0:x0 + self.input_w]

        rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
        x = rgb.astype(np.float32) / 255.0
        x = np.transpose(x, (2, 0, 1))  # CHW
        x = np.expand_dims(x, axis=0)   # NCHW
        return np.ascontiguousarray(x), x0, y0

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
        raise RuntimeError(f"Could not infer stride for N={N} at {self.input_w}x{self.input_h}")

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

    @staticmethod
    def _distance2kps(points, distances):
        kps = distances.copy()
        kps[:, 0::2] = points[:, 0:1] + distances[:, 0::2]
        kps[:, 1::2] = points[:, 1:2] + distances[:, 1::2]
        return kps

    def _decode_level(self, scores, boxes, kps):
        N = scores.shape[0]
        stride, fh, fw, A = self._infer_stride(N)
        centers = self._make_centers(fh, fw, stride, A)

        boxes_xyxy = self._distance2bbox(centers, boxes * stride)
        kps_abs = self._distance2kps(centers, kps * stride)

        sc = scores.reshape(-1)
        keep = sc >= self.conf_thresh
        return boxes_xyxy[keep], sc[keep], kps_abs[keep]

    def _decode_all(self, level_outputs):
        all_b, all_s, all_k = [], [], []
        for sc, bx, kp in level_outputs:
            b, s, k = self._decode_level(sc, bx, kp)
            if b.shape[0]:
                all_b.append(b); all_s.append(s); all_k.append(k)

        if not all_b:
            return (
                np.zeros((0, 4), np.float32),
                np.zeros((0,), np.float32),
                np.zeros((0, 10), np.float32),
            )

        boxes = np.concatenate(all_b, axis=0).astype(np.float32)
        scores = np.concatenate(all_s, axis=0).astype(np.float32)
        kps = np.concatenate(all_k, axis=0).astype(np.float32)

        boxes[:, 0] = np.clip(boxes[:, 0], 0, self.input_w - 1)
        boxes[:, 2] = np.clip(boxes[:, 2], 0, self.input_w - 1)
        boxes[:, 1] = np.clip(boxes[:, 1], 0, self.input_h - 1)
        boxes[:, 3] = np.clip(boxes[:, 3], 0, self.input_h - 1)

        keep = self._nms(boxes, scores)
        return boxes[keep], scores[keep], kps[keep]

    # ---------- Public API ----------

    def detect(self, frame_bgr: np.ndarray) -> List[FaceDetection]:
        """
        Runs detection on a single BGR frame (full RS frame).
        Returns detections with bbox/kps mapped to full-frame coords.
        """
        inp, x0, y0 = self._preprocess_center_crop(frame_bgr)
        np.copyto(self._in_host.reshape(-1), inp.reshape(-1))

        # H2D input
        self._check_cuda(cudart.cudaMemcpyAsync(
            self._in_dptr, self._in_host, self._in_nbytes,
            cudart.cudaMemcpyKind.cudaMemcpyHostToDevice, self.stream
        ))

        ok = self.context.execute_async_v2(bindings=self.bindings, stream_handle=self.stream)
        if not ok:
            raise RuntimeError("execute_async_v2 returned False")

        # D2H outputs
        level_outputs = []
        for (si, bi, ki) in self.output_groups:
            sc = self._by_index[si]
            bx = self._by_index[bi]
            kp = self._by_index[ki]

            self._check_cuda(cudart.cudaMemcpyAsync(sc["host"], sc["dptr"], sc["nbytes"],
                                                   cudart.cudaMemcpyKind.cudaMemcpyDeviceToHost, self.stream))
            self._check_cuda(cudart.cudaMemcpyAsync(bx["host"], bx["dptr"], bx["nbytes"],
                                                   cudart.cudaMemcpyKind.cudaMemcpyDeviceToHost, self.stream))
            self._check_cuda(cudart.cudaMemcpyAsync(kp["host"], kp["dptr"], kp["nbytes"],
                                                   cudart.cudaMemcpyKind.cudaMemcpyDeviceToHost, self.stream))

            level_outputs.append((
                sc["host"].reshape(sc["shape"]).astype(np.float32),
                bx["host"].reshape(bx["shape"]).astype(np.float32),
                kp["host"].reshape(kp["shape"]).astype(np.float32),
            ))

        self._check_cuda(cudart.cudaStreamSynchronize(self.stream))

        boxes, scores, kps = self._decode_all(level_outputs)

        dets: List[FaceDetection] = []
        for i in range(boxes.shape[0]):
            b = boxes[i].copy()
            b[[0, 2]] += x0
            b[[1, 3]] += y0
            kp = kps[i].copy()
            kp[0::2] += x0
            kp[1::2] += y0
            dets.append(FaceDetection(score=float(scores[i]), bbox_xyxy=b, kps=kp))
        return dets


class RealSenseD435XYZ:
    """
    D435 color+depth capture with depth aligned to color, and XYZ computation for a bbox.
    """

    def __init__(
        self,
        w: int = 640,
        h: int = 480,
        fps: int = 60,
        roi_inner_frac: float = 0.4,
        z_min_m: float = 0.2,
        z_max_m: float = 10.0,
    ):
        self.w = w
        self.h = h
        self.fps = fps
        self.roi_inner_frac = roi_inner_frac
        self.z_min_m = z_min_m
        self.z_max_m = z_max_m

        self.pipeline = rs.pipeline()
        self.config = rs.config()
        self.config.enable_stream(rs.stream.color, w, h, rs.format.bgr8, fps)
        self.config.enable_stream(rs.stream.depth, w, h, rs.format.z16, fps)
        self.profile = self.pipeline.start(self.config)

        self.align = rs.align(rs.stream.color)

        depth_sensor = self.profile.get_device().first_depth_sensor()
        self.depth_scale = depth_sensor.get_depth_scale()

        # Warm up
        for _ in range(10):
            self.pipeline.wait_for_frames()

        self._intr: Optional[rs.intrinsics] = None

    def close(self):
        self.pipeline.stop()

    def get_aligned_frames(self):
        """
        Returns:
          color_bgr: HxWx3 uint8
          depth_u16: HxW uint16 aligned to color
          intr: rs.intrinsics (color intrinsics)
        """
        frames = self.pipeline.wait_for_frames()
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

    def _robust_z_m(self, depth_u16: np.ndarray, bbox_xyxy: np.ndarray) -> Optional[float]:
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
        X, Y, Z = rs.rs2_deproject_pixel_to_point(intr, [float(u), float(v)], float(z_m))
        return float(X), float(Y), float(Z)

    def face_xyz(self, depth_u16: np.ndarray, intr: rs.intrinsics, bbox_xyxy: np.ndarray) -> Optional[Tuple[float, float, float]]:
        """
        Returns (X,Y,Z) in meters in camera coordinates, or None if depth invalid.
        Uses robust Z from the bbox central region and deprojects bbox center pixel.
        """
        z_m = self._robust_z_m(depth_u16, bbox_xyxy)
        if z_m is None:
            return None

        x1, y1, x2, y2 = bbox_xyxy
        u = int((x1 + x2) * 0.5)
        v = int((y1 + y2) * 0.5)

        return self._deproject(intr, u, v, z_m)


def main():
    cam = RealSenseD435XYZ(w=RS_W, h=RS_H, fps=RS_FPS,
                           roi_inner_frac=ROI_INNER_FRAC, z_min_m=Z_MIN_M, z_max_m=Z_MAX_M)
    det = FaceDetectorTRTSCRFD(ENGINE_PATH, INPUT_W, INPUT_H,
                               conf_thresh=CONF_THRESH, nms_iou_thresh=NMS_IOU_THRESH, strides=STRIDES)

    frame_count = 0
    last_t = time.time()
    fps_ema = None

    try:
        while True:
            color_bgr, depth_u16, intr = cam.get_aligned_frames()
            if color_bgr is None:
                continue

            faces = det.detect(color_bgr)

            # Compute XYZ for detections
            out = []
            for f in faces:
                xyz = cam.face_xyz(depth_u16, intr, f.bbox_xyxy)
                if xyz is not None:
                    out.append((f, xyz))

            # FPS
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
                    print(f"  face{i}: score={f.score:.3f} bbox=({x1:.0f},{y1:.0f})-({x2:.0f},{y2:.0f}) "
                          f"XYZ=({X:.3f},{Y:.3f},{Z:.3f}) m")

    finally:
        det.close()
        cam.close()


if __name__ == "__main__":
    main()