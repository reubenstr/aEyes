from __future__ import annotations

import argparse
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
RS_H = 360
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

    def _preprocess_letterbox(self, frame_bgr: np.ndarray):
        """
        Letterbox the frame to (input_w, input_h) while preserving the full
        width of the source image.  Black bars are added to the top and bottom
        as needed.  Returns (inp, pad_x, pad_y, scale) where pad_x / pad_y are
        the pixel offsets of the active image region inside the letterboxed
        canvas and scale is the uniform scale factor applied.

        Coordinate mapping (letterbox -> original):
            orig_x = (lbx - pad_x) / scale
            orig_y = (lby - pad_y) / scale
        """
        src_h, src_w = frame_bgr.shape[:2]

        # Fit the source into the network input using the limiting dimension.
        scale = min(self.input_w / src_w, self.input_h / src_h)
        new_w = int(round(src_w * scale))
        new_h = int(round(src_h * scale))

        resized = cv2.resize(frame_bgr, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        # Create a black canvas and paste the resized image centered.
        canvas = np.zeros((self.input_h, self.input_w, 3), dtype=np.uint8)
        pad_x = (self.input_w - new_w) // 2
        pad_y = (self.input_h - new_h) // 2
        canvas[pad_y : pad_y + new_h, pad_x : pad_x + new_w] = resized

        rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
        x = rgb.astype(np.float32) * (1.0 / 255.0)
        x = np.transpose(x, (2, 0, 1))   # CHW
        x = np.expand_dims(x, axis=0)    # NCHW
        return np.ascontiguousarray(x), pad_x, pad_y, scale

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

    def detect(self, frame_bgr: np.ndarray) -> Tuple[List[FaceDetection], np.ndarray]:
        """
        Returns (detections, letterboxed_bgr).
        letterboxed_bgr is the 480x480 canvas used for inference — useful for
        debug display when you want to visualize boxes in network coordinates.
        Bounding boxes in FaceDetection are already mapped back to the original
        frame coordinate space.
        """
        inp, pad_x, pad_y, scale = self._preprocess_letterbox(frame_bgr)

        # Keep a uint8 copy of the letterbox canvas for optional display.
        lb_canvas = (inp[0].transpose(1, 2, 0) * 255.0).clip(0, 255).astype(np.uint8)
        lb_canvas = cv2.cvtColor(lb_canvas, cv2.COLOR_RGB2BGR)

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

        boxes_lb, scores = self._decode_all(level_outputs)

        # Map letterbox coords → original frame coords.
        dets: List[FaceDetection] = []
        src_h, src_w = frame_bgr.shape[:2]
        for i in range(boxes_lb.shape[0]):
            b = boxes_lb[i].copy()
            # Undo padding then undo scale.
            b[[0, 2]] = np.clip((b[[0, 2]] - pad_x) / scale, 0, src_w - 1)
            b[[1, 3]] = np.clip((b[[1, 3]] - pad_y) / scale, 0, src_h - 1)
            dets.append(FaceDetection(score=float(scores[i]), bbox_xyxy=b))

        return dets, lb_canvas


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


def _draw_detections(
    frame_bgr: np.ndarray,
    dets: List[FaceDetection],
    xyzs: List[Optional[Tuple[float, float, float]]],
) -> np.ndarray:
    """Draw bounding boxes (and optional XYZ labels) onto a copy of frame_bgr."""
    out = frame_bgr.copy()
    for det, xyz in zip(dets, xyzs):
        x1, y1, x2, y2 = det.bbox_xyxy.astype(int)
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)

        label = f"{det.score:.2f}"
        if xyz is not None:
            label += f"  {xyz[0]:.2f},{xyz[1]:.2f},{xyz[2]:.2f}m"

        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        ty = max(y1 - 4, th + 2)
        cv2.rectangle(out, (x1, ty - th - 2), (x1 + tw + 2, ty + 2), (0, 255, 0), -1)
        cv2.putText(
            out, label, (x1 + 1, ty),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA,
        )
    return out


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

        dets, _ = self.det.detect(color_bgr)

        closest_point = None
        min_dist = float("inf")

        for f in dets:
            xyz = self.cam.face_xyz(depth_u16, intr, f.bbox_xyxy)
            if xyz is None:
                continue

            points = [xyz] if isinstance(xyz[0], (int, float)) else xyz

            for x, y, z in points:
                if not math.isfinite(x) or not math.isfinite(y) or not math.isfinite(z):
                    continue
                dist = x * x + y * y + z * z
                if dist < min_dist:
                    min_dist = dist
                    closest_point = (x, y, z)

        return closest_point

    def run_display(self):
        """Blocking loop: capture → detect → display with bounding boxes. Press q to quit."""
        window_name = "Face Detector"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

        frame_idx = 0
        fps = 0.0
        fps_alpha = 0.1  # EMA smoothing factor
        t_last = time.perf_counter()

        try:
            while True:
                color_bgr, depth_u16, intr = self.cam.get_aligned_frames()
                if color_bgr is None:
                    continue

                dets, _ = self.det.detect(color_bgr)

                xyzs: List[Optional[Tuple[float, float, float]]] = []
                for f in dets:
                    xyzs.append(self.cam.face_xyz(depth_u16, intr, f.bbox_xyxy))

                vis = _draw_detections(color_bgr, dets, xyzs)

                # --- FPS overlay ---
                t_now = time.perf_counter()
                instant_fps = 1.0 / max(t_now - t_last, 1e-9)
                t_last = t_now
                fps = fps + fps_alpha * (instant_fps - fps) if frame_idx > 0 else instant_fps

                fps_label = f"FPS: {fps:.1f}"
                (fw, fh), _ = cv2.getTextSize(fps_label, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)
                cv2.rectangle(vis, (8, 8), (8 + fw + 6, 8 + fh + 8), (0, 0, 0), -1)
                cv2.putText(
                    vis, fps_label, (11, 8 + fh + 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2, cv2.LINE_AA,
                )

                cv2.imshow(window_name, vis)

                frame_idx += 1
                if frame_idx % PRINT_EVERY_N_FRAMES == 0:
                    print(f"[frame {frame_idx}] {len(dets)} face(s) detected  FPS={fps:.1f}")
                    for i, (f, xyz) in enumerate(zip(dets[:PRINT_TOP_K], xyzs[:PRINT_TOP_K])):
                        print(f"  [{i}] score={f.score:.3f}  xyz={xyz}")

                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
        finally:
            cv2.destroyAllWindows()

    def shutdown(self):
        self.det.close()
        self.cam.close()


# ------------------------------------------------------------------ #
#  CLI entry-point                                                     #
# ------------------------------------------------------------------ #

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="RealSense + TRT face detector")
    p.add_argument(
        "--display",
        action="store_true",
        default=False,
        help="Open an OpenCV window showing the live stream with bounding boxes.",
    )
    return p.parse_args()


def main():
    args = _parse_args()
    detector = Detector()
    try:
        if args.display:
            detector.run_display()
        else:
            # Headless loop — just print closest face.
            frame_idx = 0
            while True:
                pt = detector.get_closest_point()
                frame_idx += 1
                if frame_idx % PRINT_EVERY_N_FRAMES == 0:
                    print(f"[frame {frame_idx}] closest={pt}")
    finally:
        detector.shutdown()


if __name__ == "__main__":
    main()