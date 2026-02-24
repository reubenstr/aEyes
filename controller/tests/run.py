#!/usr/bin/env python3
"""
RealSense (color) -> TensorRT -> SCRFD-style face detection (decode + NMS) using cuda-python (no PyCUDA).

This script is written to match what your engine bindings show:
- 1 input:  (1, 3, 1, 1)  => dynamic, you MUST set the real shape (1,3,H,W) on the context
- 9 outputs grouped as 3 feature levels, each level has:
    scores: (N,1)
    boxes:  (N,4)
    kps:    (N,10)
  repeated 3 times (typically strides 8/16/32)

Your output names are numeric (e.g., 446, 449, 452...), which is fine.

Dependencies:
  pip3 install pyrealsense2 opencv-python numpy cuda-python
  (Prefer system OpenCV on Jetson; pip OpenCV may be non-accelerated.)

Notes:
- For max FPS/lowest latency, remove cv2.imshow and drawing.
- This is CPU-side decode + NMS; inference is GPU (TensorRT).
"""

import time
import numpy as np
import cv2
import pyrealsense2 as rs
import tensorrt as trt
from cuda import cudart


# ---------------------- User settings ----------------------
ENGINE_PATH = "face_fp16.engine"

# Must match what your engine expects at runtime
INPUT_W = 640
INPUT_H = 640

# RealSense stream settings (can differ from INPUT_W/H)
RS_W = 640
RS_H = 480
RS_FPS = 60

CONF_THRESH = 0.5
NMS_IOU_THRESH = 0.4

# If your SCRFD variant uses different strides, adjust here:
STRIDES_CANDIDATES = (8, 16, 32)
# ----------------------------------------------------------


TRT_LOGGER = trt.Logger(trt.Logger.WARNING)


def check_cuda(ret):
    """
    Normalize cuda-python (cudart) returns.

    Accepts:
      - cudaError_t
      - (cudaError_t,)
      - (cudaError_t, value)
      - (cudaError_t, v1, v2, ...) -> returns remaining values (tuple)
    """
    if not isinstance(ret, tuple):
        if ret != cudart.cudaError_t.cudaSuccess:
            raise RuntimeError(f"CUDA error: {ret}")
        return None

    if len(ret) == 0:
        raise RuntimeError("CUDA call returned empty tuple (unexpected).")

    err = ret[0]
    if err != cudart.cudaError_t.cudaSuccess:
        raise RuntimeError(f"CUDA error: {err}")

    if len(ret) == 1:
        return None
    if len(ret) == 2:
        return ret[1]
    return ret[1:]


def load_engine(engine_path: str) -> trt.ICudaEngine:
    with open(engine_path, "rb") as f, trt.Runtime(TRT_LOGGER) as runtime:
        engine = runtime.deserialize_cuda_engine(f.read())
    if engine is None:
        raise RuntimeError(f"Failed to deserialize engine: {engine_path}")
    return engine


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


def preprocess_bgr(frame_bgr: np.ndarray) -> np.ndarray:
    """
    Minimal preprocessing (CPU):
    - resize to INPUT_W/H
    - BGR -> RGB
    - float32, [0,1]
    - NCHW
    Adjust if your model expects mean/std.
    """
    resized = cv2.resize(frame_bgr, (INPUT_W, INPUT_H), interpolation=cv2.INTER_LINEAR)
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
    x = rgb.astype(np.float32) / 255.0
    x = np.transpose(x, (2, 0, 1))  # CHW
    x = np.expand_dims(x, axis=0)   # NCHW
    return np.ascontiguousarray(x)


def iou_one_to_many(box, boxes):
    """IoU between one box and many boxes. boxes shape: (M,4)."""
    x1 = np.maximum(box[0], boxes[:, 0])
    y1 = np.maximum(box[1], boxes[:, 1])
    x2 = np.minimum(box[2], boxes[:, 2])
    y2 = np.minimum(box[3], boxes[:, 3])

    inter_w = np.maximum(0.0, x2 - x1)
    inter_h = np.maximum(0.0, y2 - y1)
    inter = inter_w * inter_h

    area_box = (box[2] - box[0]) * (box[3] - box[1])
    area_boxes = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])

    union = area_box + area_boxes - inter + 1e-9
    return inter / union


def nms(boxes, scores, iou_thresh):
    """Standard NMS. boxes: (N,4), scores: (N,). returns indices kept."""
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


def distance2bbox(points, distances):
    """
    points: (N,2) centers (cx,cy)
    distances: (N,4) (l,t,r,b) in pixels
    returns: (N,4) boxes (x1,y1,x2,y2)
    """
    x1 = points[:, 0] - distances[:, 0]
    y1 = points[:, 1] - distances[:, 1]
    x2 = points[:, 0] + distances[:, 2]
    y2 = points[:, 1] + distances[:, 3]
    return np.stack([x1, y1, x2, y2], axis=1)


def distance2kps(points, distances):
    """
    points: (N,2) centers
    distances: (N,10) (dx1,dy1, dx2,dy2, ... dx5,dy5) in pixels
    returns: (N,10) absolute landmark coords
    """
    kps = distances.copy()
    kps[:, 0::2] = points[:, 0:1] + distances[:, 0::2]
    kps[:, 1::2] = points[:, 1:1+1] + distances[:, 1::2]
    return kps


def infer_stride(N, H, W, candidates=STRIDES_CANDIDATES):
    """
    Given number of anchors N for a feature level, infer stride and anchors-per-location.
    We assume SCRFD-like: N = (H/stride)*(W/stride)*A, where A is small integer (often 2).
    """
    for s in candidates:
        fh = H // s
        fw = W // s
        loc = fh * fw
        if loc <= 0:
            continue
        if N % loc == 0:
            A = N // loc
            if A in (1, 2, 4, 6):  # common small anchor counts
                return s, fh, fw, A
    return None


def make_centers(fh, fw, stride, A):
    """
    Create anchor centers for SCRFD:
    - grid centers at (x+0.5, y+0.5)*stride
    - repeated A times per location
    returns points: (fh*fw*A, 2)
    """
    xs = (np.arange(fw) + 0.5) * stride
    ys = (np.arange(fh) + 0.5) * stride
    xv, yv = np.meshgrid(xs, ys)
    centers = np.stack([xv.reshape(-1), yv.reshape(-1)], axis=1)  # (fh*fw,2)
    if A > 1:
        centers = np.repeat(centers, A, axis=0)
    return centers.astype(np.float32)


def decode_scrfd_level(scores, boxes, kps, input_h, input_w):
    """
    Decode one SCRFD feature level.
    scores: (N,1) float
    boxes:  (N,4) float distances
    kps:    (N,10) float distances
    returns boxes_xyxy (M,4), scores (M,), kps (M,10) filtered by CONF_THRESH
    """
    N = scores.shape[0]
    info = infer_stride(N, input_h, input_w)
    if info is None:
        raise RuntimeError(f"Could not infer stride for N={N} at input {input_w}x{input_h}")
    stride, fh, fw, A = info

    # centers and decode distances -> absolute coords
    centers = make_centers(fh, fw, stride, A)  # (N,2)

    # SCRFD bbox/kps predictions are typically in "stride units" (or normalized to stride)
    # Multiply by stride to convert to pixels.
    boxes_pix = boxes * stride
    kps_pix = kps * stride

    boxes_xyxy = distance2bbox(centers, boxes_pix)
    kps_abs = distance2kps(centers, kps_pix)

    sc = scores.reshape(-1)
    keep = sc >= CONF_THRESH

    return boxes_xyxy[keep], sc[keep], kps_abs[keep]


def decode_scrfd_all(level_outputs, input_h, input_w):
    """
    level_outputs: list of tuples (scores, boxes, kps) for each feature level.
    returns final boxes, scores, kps after NMS
    """
    all_boxes = []
    all_scores = []
    all_kps = []

    for (sc, bx, kp) in level_outputs:
        b, s, k = decode_scrfd_level(sc, bx, kp, input_h, input_w)
        if b.shape[0] > 0:
            all_boxes.append(b)
            all_scores.append(s)
            all_kps.append(k)

    if not all_boxes:
        return np.zeros((0, 4), dtype=np.float32), np.zeros((0,), dtype=np.float32), np.zeros((0, 10), dtype=np.float32)

    boxes = np.concatenate(all_boxes, axis=0).astype(np.float32)
    scores = np.concatenate(all_scores, axis=0).astype(np.float32)
    kps = np.concatenate(all_kps, axis=0).astype(np.float32)

    # Clip boxes to input bounds
    boxes[:, 0] = np.clip(boxes[:, 0], 0, input_w - 1)
    boxes[:, 2] = np.clip(boxes[:, 2], 0, input_w - 1)
    boxes[:, 1] = np.clip(boxes[:, 1], 0, input_h - 1)
    boxes[:, 3] = np.clip(boxes[:, 3], 0, input_h - 1)

    keep = nms(boxes, scores, NMS_IOU_THRESH)
    return boxes[keep], scores[keep], kps[keep]


def allocate_io_dynamic(engine: trt.ICudaEngine, context: trt.IExecutionContext, input_shape_nchw):
    """
    Allocate buffers AFTER setting the binding shape (dynamic shapes).
    Uses context.get_binding_shape(i) so output shapes become concrete (non-zero).
    """
    stream = check_cuda(cudart.cudaStreamCreate())

    # For engines with optimization profiles, profile 0 is typical default
    # (execute_async_v2 uses the active profile on the context)
    # Some TRT builds require this call; harmless if not needed.
    try:
        context.set_optimization_profile_async(0, stream)
    except Exception:
        pass

    # Identify input binding index and set actual shape
    input_indices = [i for i in range(engine.num_bindings) if engine.binding_is_input(i)]
    if len(input_indices) != 1:
        raise RuntimeError(f"Expected 1 input binding, got {len(input_indices)}")
    in_idx = input_indices[0]

    if not context.set_binding_shape(in_idx, tuple(input_shape_nchw)):
        raise RuntimeError(f"Failed to set binding shape {input_shape_nchw} on input index {in_idx}")

    if not context.all_binding_shapes_specified:
        raise RuntimeError("Not all binding shapes specified after setting input shape.")

    bindings = [0] * engine.num_bindings
    inputs = {}
    outputs = {}

    for i in range(engine.num_bindings):
        name = engine.get_binding_name(i)
        dtype = trt.nptype(engine.get_binding_dtype(i))
        shape = tuple(context.get_binding_shape(i))  # NOTE: use context shape (concrete)

        n_elems = int(np.prod(shape))
        nbytes = n_elems * np.dtype(dtype).itemsize
        if nbytes <= 0:
            raise RuntimeError(f"Computed nbytes <= 0 for binding {i} {name} shape={shape}")

        host = np.empty(n_elems, dtype=dtype)
        dptr = check_cuda(cudart.cudaMalloc(nbytes))

        bindings[i] = int(dptr)
        io = {"index": i, "name": name, "host": host, "device": dptr, "shape": shape, "dtype": dtype, "nbytes": nbytes}

        if engine.binding_is_input(i):
            inputs[name] = io
        else:
            outputs[name] = io

    return bindings, inputs, outputs, stream


def free_io(inputs, outputs, stream):
    for io in list(inputs.values()) + list(outputs.values()):
        try:
            check_cuda(cudart.cudaFree(io["device"]))
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

    # Allocate buffers after setting dynamic shapes
    bindings, inputs, outputs, stream = allocate_io_dynamic(engine, context, (1, 3, INPUT_H, INPUT_W))

    # Map outputs into 3 levels of (score, box, kps) by binding index order.
    # Based on your binding printout: (1,2,3), (4,5,6), (7,8,9)
    out_by_index = {}
    for name, io in outputs.items():
        out_by_index[io["index"]] = (name, io)

    level_indices = [(1, 2, 3), (4, 5, 6), (7, 8, 9)]
    levels = []
    for (si, bi, ki) in level_indices:
        if si not in out_by_index or bi not in out_by_index or ki not in out_by_index:
            raise RuntimeError("Output bindings do not match expected SCRFD grouping. Re-check bindings.")
        levels.append((out_by_index[si][1], out_by_index[bi][1], out_by_index[ki][1]))

    input_name = next(iter(inputs.keys()))
    host_in = inputs[input_name]["host"]

    last_t = time.time()
    fps_ema = None

    try:
        while True:
            frames = pipeline.wait_for_frames()
            color = frames.get_color_frame()
            if not color:
                continue

            frame = np.asanyarray(color.get_data())
            orig_h, orig_w = frame.shape[:2]

            inp = preprocess_bgr(frame)

            # Copy to host input buffer
            np.copyto(host_in.reshape(-1), inp.reshape(-1))

            # H2D input
            check_cuda(cudart.cudaMemcpyAsync(
                inputs[input_name]["device"],
                host_in,
                inputs[input_name]["nbytes"],
                cudart.cudaMemcpyKind.cudaMemcpyHostToDevice,
                stream
            ))

            # Execute
            ok = context.execute_async_v2(bindings=bindings, stream_handle=stream)
            if not ok:
                raise RuntimeError("TensorRT execute_async_v2 returned False")

            # D2H all outputs needed for decode
            for (sc_io, bx_io, kp_io) in levels:
                for io in (sc_io, bx_io, kp_io):
                    check_cuda(cudart.cudaMemcpyAsync(
                        io["host"],
                        io["device"],
                        io["nbytes"],
                        cudart.cudaMemcpyKind.cudaMemcpyDeviceToHost,
                        stream
                    ))

            check_cuda(cudart.cudaStreamSynchronize(stream))

            # Reshape and decode
            level_outputs = []
            for (sc_io, bx_io, kp_io) in levels:
                sc = sc_io["host"].reshape(sc_io["shape"])
                bx = bx_io["host"].reshape(bx_io["shape"])
                kp = kp_io["host"].reshape(kp_io["shape"])
                level_outputs.append((sc.astype(np.float32), bx.astype(np.float32), kp.astype(np.float32)))

            boxes_in, scores, kps_in = decode_scrfd_all(level_outputs, INPUT_H, INPUT_W)

            # Map boxes/landmarks from INPUT_W/H back to original frame size
            sx = orig_w / float(INPUT_W)
            sy = orig_h / float(INPUT_H)

            boxes = boxes_in.copy()
            boxes[:, 0] *= sx
            boxes[:, 2] *= sx
            boxes[:, 1] *= sy
            boxes[:, 3] *= sy

            kps = kps_in.copy()
            kps[:, 0::2] *= sx
            kps[:, 1::2] *= sy

            # Visualization (remove for max FPS)
            for (b, s, kp) in zip(boxes, scores, kps):
                x1, y1, x2, y2 = b.astype(int).tolist()
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, f"{float(s):.2f}", (x1, max(0, y1 - 5)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                # 5 landmarks
                for j in range(5):
                    cx = int(kp[2 * j])
                    cy = int(kp[2 * j + 1])
                    cv2.circle(frame, (cx, cy), 2, (0, 255, 255), -1)

            now = time.time()
            fps = 1.0 / max(1e-6, now - last_t)
            last_t = now
            fps_ema = fps if fps_ema is None else (0.9 * fps_ema + 0.1 * fps)

            cv2.putText(frame, f"FPS: {fps_ema:.1f}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)

            cv2.imshow("SCRFD Face Detections", frame)
            if (cv2.waitKey(1) & 0xFF) == 27:  # ESC
                break

    finally:
        pipeline.stop()
        cv2.destroyAllWindows()
        free_io(inputs, outputs, stream)


if __name__ == "__main__":
    main()