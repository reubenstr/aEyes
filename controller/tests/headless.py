#!/usr/bin/env python3
"""
Headless RealSense (640x480) -> center-crop 480x480 -> TensorRT SCRFD decode -> prints FPS + top detections.
No cv2.imshow (safe for headless).

Assumptions:
- Engine is built for fixed input (1,3,480,480) and SCRFD-style outputs:
  (scores, boxes, kps) for 3 feature levels.
- Outputs are exactly as in your 640x640 run but with smaller counts. The script
  groups outputs by binding index: (1,2,3), (4,5,6), (7,8,9).

Dependencies:
  python3 -m pip install numpy cuda-python pyrealsense2
  (OpenCV should be the JetPack system build; avoid pip opencv-python if possible.)
"""

import time
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

PRINT_EVERY_N_FRAMES = 1
PRINT_TOP_K = 3
# ----------------------------------------------------------


TRT_LOGGER = trt.Logger(trt.Logger.WARNING)


def check_cuda(ret):
    """Normalize cuda-python (cudart) returns."""
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


def load_engine(path: str) -> trt.ICudaEngine:
    with open(path, "rb") as f, trt.Runtime(TRT_LOGGER) as rt:
        e = rt.deserialize_cuda_engine(f.read())
    if e is None:
        raise RuntimeError(f"Failed to load engine: {path}")
    return e


def print_bindings(engine: trt.ICudaEngine):
    print("=== TensorRT bindings ===")
    for i in range(engine.num_bindings):
        print(
            f"{i:2d}  {engine.get_binding_name(i):30s}  "
            f"{'IN ' if engine.binding_is_input(i) else 'OUT'}  "
            f"shape={tuple(engine.get_binding_shape(i))}  "
            f"dtype={engine.get_binding_dtype(i)}"
        )
    print("========================")


def preprocess_bgr_center_crop_480(frame_bgr: np.ndarray):
    """
    Center-crop INPUT_WxINPUT_H from a RS_WxRS_H frame.
    For RS 640x480 and INPUT 480x480, this is a horizontal crop (x offset 80), y offset 0.
    Returns:
      inp: float32 NCHW tensor
      x0, y0: crop offsets in original frame pixels
    """
    h, w = frame_bgr.shape[:2]
    crop_w, crop_h = INPUT_W, INPUT_H
    if w < crop_w or h < crop_h:
        raise ValueError(f"Frame too small for crop: frame={w}x{h}, crop={crop_w}x{crop_h}")

    x0 = (w - crop_w) // 2
    y0 = (h - crop_h) // 2
    roi = frame_bgr[y0:y0 + crop_h, x0:x0 + crop_w]

    rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
    x = rgb.astype(np.float32) / 255.0
    x = np.transpose(x, (2, 0, 1))  # CHW
    x = np.expand_dims(x, axis=0)   # NCHW
    return np.ascontiguousarray(x), x0, y0


def iou_one_to_many(box, boxes):
    x1 = np.maximum(box[0], boxes[:, 0])
    y1 = np.maximum(box[1], boxes[:, 1])
    x2 = np.minimum(box[2], boxes[:, 2])
    y2 = np.minimum(box[3], boxes[:, 3])
    inter = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    area_a = (box[2] - box[0]) * (box[3] - box[1])
    area_b = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    return inter / (area_a + area_b - inter + 1e-9)


def nms(boxes, scores, iou_thresh):
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
        ious = iou_one_to_many(boxes[i], boxes[rest])
        order = rest[ious < iou_thresh]
    return np.array(keep, dtype=np.int64)


def infer_stride(N, H, W):
    """
    Infer stride and anchors-per-location A from tensor length N.
    N = (H/stride)*(W/stride)*A
    """
    for s in STRIDES:
        fh, fw = H // s, W // s
        loc = fh * fw
        if loc > 0 and (N % loc == 0):
            A = N // loc
            if A in (1, 2, 4, 6):
                return s, fh, fw, A
    raise RuntimeError(f"Could not infer stride for N={N} at {W}x{H}")


def make_centers(fh, fw, stride, A):
    xs = (np.arange(fw) + 0.5) * stride
    ys = (np.arange(fh) + 0.5) * stride
    xv, yv = np.meshgrid(xs, ys)
    centers = np.stack([xv.reshape(-1), yv.reshape(-1)], axis=1)  # (fh*fw,2)
    if A > 1:
        centers = np.repeat(centers, A, axis=0)
    return centers.astype(np.float32)


def distance2bbox(points, distances):
    x1 = points[:, 0] - distances[:, 0]
    y1 = points[:, 1] - distances[:, 1]
    x2 = points[:, 0] + distances[:, 2]
    y2 = points[:, 1] + distances[:, 3]
    return np.stack([x1, y1, x2, y2], axis=1)


def distance2kps(points, distances):
    kps = distances.copy()
    kps[:, 0::2] = points[:, 0:1] + distances[:, 0::2]
    kps[:, 1::2] = points[:, 1:2] + distances[:, 1::2]
    return kps


def decode_level(scores, boxes, kps):
    N = scores.shape[0]
    stride, fh, fw, A = infer_stride(N, INPUT_H, INPUT_W)
    centers = make_centers(fh, fw, stride, A)

    boxes_xyxy = distance2bbox(centers, boxes * stride)
    kps_abs = distance2kps(centers, kps * stride)

    sc = scores.reshape(-1)
    keep = sc >= CONF_THRESH
    return boxes_xyxy[keep], sc[keep], kps_abs[keep]


def decode_all(levels):
    all_b, all_s, all_k = [], [], []
    for sc, bx, kp in levels:
        b, s, k = decode_level(sc, bx, kp)
        if b.shape[0]:
            all_b.append(b)
            all_s.append(s)
            all_k.append(k)

    if not all_b:
        return (
            np.zeros((0, 4), np.float32),
            np.zeros((0,), np.float32),
            np.zeros((0, 10), np.float32),
        )

    boxes = np.concatenate(all_b, axis=0).astype(np.float32)
    scores = np.concatenate(all_s, axis=0).astype(np.float32)
    kps = np.concatenate(all_k, axis=0).astype(np.float32)

    # Clip to input crop bounds
    boxes[:, 0] = np.clip(boxes[:, 0], 0, INPUT_W - 1)
    boxes[:, 2] = np.clip(boxes[:, 2], 0, INPUT_W - 1)
    boxes[:, 1] = np.clip(boxes[:, 1], 0, INPUT_H - 1)
    boxes[:, 3] = np.clip(boxes[:, 3], 0, INPUT_H - 1)

    keep = nms(boxes, scores, NMS_IOU_THRESH)
    return boxes[keep], scores[keep], kps[keep]


def allocate_io(engine: trt.ICudaEngine, context: trt.IExecutionContext):
    """
    Allocate host and device buffers for all bindings.
    This assumes fixed engine shapes (not dynamic profiles).
    """
    stream = check_cuda(cudart.cudaStreamCreate())

    # Set shape anyway (TRT warns about deprecations; function still works)
    in_idx = [i for i in range(engine.num_bindings) if engine.binding_is_input(i)][0]
    context.set_binding_shape(in_idx, (1, 3, INPUT_H, INPUT_W))

    bindings = [0] * engine.num_bindings
    bufs = []

    for i in range(engine.num_bindings):
        name = engine.get_binding_name(i)
        dtype = trt.nptype(engine.get_binding_dtype(i))
        shape = tuple(context.get_binding_shape(i))
        n = int(np.prod(shape))
        nbytes = n * np.dtype(dtype).itemsize
        if nbytes <= 0:
            raise RuntimeError(f"Invalid binding size for {i} {name}: shape={shape}")

        host = np.empty(n, dtype=dtype)
        dptr = check_cuda(cudart.cudaMalloc(nbytes))

        bindings[i] = int(dptr)
        bufs.append((i, name, host, dptr, shape, nbytes, engine.binding_is_input(i)))

    return bindings, bufs, stream


def free_io(bufs, stream):
    for (_, _, _, dptr, _, _, _) in bufs:
        try:
            check_cuda(cudart.cudaFree(dptr))
        except Exception:
            pass
    try:
        check_cuda(cudart.cudaStreamDestroy(stream))
    except Exception:
        pass


def main():
    # RealSense
    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.color, RS_W, RS_H, rs.format.bgr8, RS_FPS)
    pipeline.start(config)
    for _ in range(10):
        pipeline.wait_for_frames()

    # TensorRT
    engine = load_engine(ENGINE_PATH)
    print_bindings(engine)

    context = engine.create_execution_context()
    if context is None:
        raise RuntimeError("Failed to create TensorRT execution context.")

    bindings, bufs, stream = allocate_io(engine, context)

    # Index map
    by_index = {i: (name, host, dptr, shape, nbytes, is_in) for (i, name, host, dptr, shape, nbytes, is_in) in bufs}

    # Input at binding 0
    in_host = by_index[0][1]
    in_dptr = by_index[0][2]
    in_nbytes = by_index[0][4]

    # Output groups by binding indices (SCRFD)
    level_indices = [(1, 2, 3), (4, 5, 6), (7, 8, 9)]

    frame_count = 0
    last_t = time.time()
    fps_ema = None

    try:
        while True:
            frames = pipeline.wait_for_frames()
            color = frames.get_color_frame()
            if not color:
                continue

            frame = np.asanyarray(color.get_data())  # 640x480 BGR
            inp, x0, y0 = preprocess_bgr_center_crop_480(frame)

            np.copyto(in_host.reshape(-1), inp.reshape(-1))

            # H2D input
            check_cuda(cudart.cudaMemcpyAsync(
                in_dptr,
                in_host,
                in_nbytes,
                cudart.cudaMemcpyKind.cudaMemcpyHostToDevice,
                stream
            ))

            ok = context.execute_async_v2(bindings=bindings, stream_handle=stream)
            if not ok:
                raise RuntimeError("execute_async_v2 returned False")

            # D2H outputs
            level_outputs = []
            for (si, bi, ki) in level_indices:
                sc_host, sc_dptr, sc_shape, sc_nbytes = by_index[si][1], by_index[si][2], by_index[si][3], by_index[si][4]
                bx_host, bx_dptr, bx_shape, bx_nbytes = by_index[bi][1], by_index[bi][2], by_index[bi][3], by_index[bi][4]
                kp_host, kp_dptr, kp_shape, kp_nbytes = by_index[ki][1], by_index[ki][2], by_index[ki][3], by_index[ki][4]

                check_cuda(cudart.cudaMemcpyAsync(sc_host, sc_dptr, sc_nbytes,
                                                 cudart.cudaMemcpyKind.cudaMemcpyDeviceToHost, stream))
                check_cuda(cudart.cudaMemcpyAsync(bx_host, bx_dptr, bx_nbytes,
                                                 cudart.cudaMemcpyKind.cudaMemcpyDeviceToHost, stream))
                check_cuda(cudart.cudaMemcpyAsync(kp_host, kp_dptr, kp_nbytes,
                                                 cudart.cudaMemcpyKind.cudaMemcpyDeviceToHost, stream))

                level_outputs.append((
                    sc_host.reshape(sc_shape).astype(np.float32),
                    bx_host.reshape(bx_shape).astype(np.float32),
                    kp_host.reshape(kp_shape).astype(np.float32),
                ))

            check_cuda(cudart.cudaStreamSynchronize(stream))

            # Decode on CPU
            boxes, scores, kps = decode_all(level_outputs)

            # Map from crop coords (480x480) back to original frame (640x480) by adding offsets
            if boxes.shape[0] > 0:
                boxes_o = boxes.copy()
                boxes_o[:, [0, 2]] += x0
                boxes_o[:, [1, 3]] += y0
            else:
                boxes_o = boxes

            # FPS stats
            now = time.time()
            fps = 1.0 / max(1e-6, now - last_t)
            last_t = now
            fps_ema = fps if fps_ema is None else (0.9 * fps_ema + 0.1 * fps)

            frame_count += 1
            if frame_count % PRINT_EVERY_N_FRAMES == 0:
                print(f"FPS(EMA): {fps_ema:.1f}  faces: {boxes_o.shape[0]}")
                for i in range(min(PRINT_TOP_K, boxes_o.shape[0])):
                    x1, y1, x2, y2 = boxes_o[i]
                    print(f"  face{i}: ({x1:.1f},{y1:.1f})-({x2:.1f},{y2:.1f}) score={scores[i]:.3f}")

    finally:
        pipeline.stop()
        free_io(bufs, stream)


if __name__ == "__main__":
    main()