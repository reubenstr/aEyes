# Barebones: RealSense -> SCRFD ONNX -> ONNX Runtime TensorRT EP -> draw boxes
#
# deps:
#   pip install numpy opencv-python pyrealsense2
#   (You must have an ONNX Runtime build that includes TensorrtExecutionProvider on Jetson)
#
# run:
#   python scrfd_trt_realsense.py --model scrfd_1g.onnx

import argparse
import os
import cv2
import numpy as np
import onnxruntime as ort
import pyrealsense2 as rs

def letterbox_bgr(img, new_w=640, new_h=640, color=(0, 0, 0)):
    h, w = img.shape[:2]
    scale = min(new_w / w, new_h / h)
    rw, rh = int(round(w * scale)), int(round(h * scale))
    resized = cv2.resize(img, (rw, rh), interpolation=cv2.INTER_LINEAR)

    pad_x = new_w - rw
    pad_y = new_h - rh
    left = pad_x // 2
    right = pad_x - left
    top = pad_y // 2
    bottom = pad_y - top

    out = cv2.copyMakeBorder(resized, top, bottom, left, right,
                             borderType=cv2.BORDER_CONSTANT, value=color)
    return out, scale, left, top

def nms_xyxy(boxes, scores, iou_thresh=0.4):
    if len(boxes) == 0:
        return np.array([], dtype=np.int32)
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1 + 1.0) * (y2 - y1 + 1.0)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        w = np.maximum(0.0, xx2 - xx1 + 1.0)
        h = np.maximum(0.0, yy2 - yy1 + 1.0)
        inter = w * h
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)

        inds = np.where(iou <= iou_thresh)[0]
        order = order[inds + 1]
    return np.array(keep, dtype=np.int32)

def distance2bbox(points, dist):
    # dist: l,t,r,b
    x1 = points[:, 0] - dist[:, 0]
    y1 = points[:, 1] - dist[:, 1]
    x2 = points[:, 0] + dist[:, 2]
    y2 = points[:, 1] + dist[:, 3]
    return np.stack([x1, y1, x2, y2], axis=1)

class SCRFD_TRTEP:
    def __init__(self, onnx_path, engine_cache_dir="./trt_cache"):
        os.makedirs(engine_cache_dir, exist_ok=True)

        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        # TensorRT EP provider options (common + safe defaults)
        trt_opts = {
            "trt_engine_cache_enable": "1",
            "trt_engine_cache_path": engine_cache_dir,
            "trt_fp16_enable": "1",               # FP16 is typically best on Xavier
            "trt_int8_enable": "0",
            "trt_max_workspace_size": str(1 << 30),  # 1GB workspace (adjust if needed)
        }

        providers = [
            ("TensorrtExecutionProvider", trt_opts),
            ("CUDAExecutionProvider", {}),
            ("CPUExecutionProvider", {}),
        ]

        self.sess = ort.InferenceSession(onnx_path, sess_options=so, providers=providers)

        self.inp = self.sess.get_inputs()[0]
        shp = self.inp.shape  # [N,C,H,W] possibly dynamic
        self.inp_h = int(shp[2]) if isinstance(shp[2], int) else 640
        self.inp_w = int(shp[3]) if isinstance(shp[3], int) else 640

        self.inp_name = self.inp.name
        self.out_names = [o.name for o in self.sess.get_outputs()]
        self.has_kps = (len(self.out_names) == 9)
        self.fpn_strides = [8, 16, 32]

        print("Available EPs:", ort.get_available_providers())
        print("Session EPs:", self.sess.get_providers())
        if "TensorrtExecutionProvider" not in self.sess.get_providers():
            raise RuntimeError("TensorRT EP not active. You need an ORT build with TensorrtExecutionProvider.")

    def preprocess(self, bgr):
        lb, scale, left, top = letterbox_bgr(bgr, self.inp_w, self.inp_h)
        x = lb.astype(np.float32)
        x = (x - 127.5) / 128.0  # common SCRFD normalization
        x = np.transpose(x, (2, 0, 1))[None, ...]  # NCHW
        return x, scale, left, top

    def detect(self, bgr, score_thresh=0.5, iou_thresh=0.4, top_k=5000):
        x, scale, left, top = self.preprocess(bgr)
        outs = self.sess.run(self.out_names, {self.inp_name: x})

        det_boxes, det_scores = [], []
        idx = 0
        for stride in self.fpn_strides:
            scores = np.squeeze(outs[idx])
            bboxes = np.squeeze(outs[idx + 1])
            idx += 3 if self.has_kps else 2

            scores = scores.reshape(-1)
            if bboxes.ndim == 3:  # (4,H,W)
                bboxes = np.transpose(bboxes, (1, 2, 0)).reshape(-1, 4)
            else:
                bboxes = bboxes.reshape(-1, 4)

            fh = self.inp_h // stride
            fw = self.inp_w // stride
            ys, xs = np.mgrid[0:fh, 0:fw]
            centers = np.stack([(xs + 0.5) * stride, (ys + 0.5) * stride], axis=-1).reshape(-1, 2)

            boxes = distance2bbox(centers, bboxes)
            keep = np.where(scores >= score_thresh)[0]
            if keep.size == 0:
                continue

            boxes = boxes[keep]
            sc = scores[keep]

            if boxes.shape[0] > top_k:
                order = sc.argsort()[::-1][:top_k]
                boxes = boxes[order]
                sc = sc[order]

            det_boxes.append(boxes)
            det_scores.append(sc)

        if not det_boxes:
            return np.zeros((0, 4), dtype=np.float32), np.zeros((0,), dtype=np.float32)

        boxes = np.concatenate(det_boxes, axis=0)
        scores = np.concatenate(det_scores, axis=0)

        keep = nms_xyxy(boxes, scores, iou_thresh=iou_thresh)
        boxes = boxes[keep]
        scores = scores[keep]

        # unletterbox to original
        boxes[:, [0, 2]] = (boxes[:, [0, 2]] - left) / scale
        boxes[:, [1, 3]] = (boxes[:, [1, 3]] - top) / scale
        return boxes, scores

def realsense_color_stream(width=1280, height=720, fps=30):
    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.color, width, height, rs.format.bgr8, fps)
    profile = pipeline.start(config)
    return pipeline, profile

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--score", type=float, default=0.5)
    ap.add_argument("--iou", type=float, default=0.4)
    ap.add_argument("--cache", default="./trt_cache")
    ap.add_argument("--w", type=int, default=1280)
    ap.add_argument("--h", type=int, default=720)
    ap.add_argument("--fps", type=int, default=30)
    args = ap.parse_args()

    det = SCRFD_TRTEP(args.model, engine_cache_dir=args.cache)

    pipeline, _ = realsense_color_stream(args.w, args.h, args.fps)

    try:
        while True:
            frames = pipeline.wait_for_frames()
            color = frames.get_color_frame()
            if not color:
                continue
            frame = np.asanyarray(color.get_data())  # BGR8

            boxes, scores = det.detect(frame, score_thresh=args.score, iou_thresh=args.iou)

            for (x1, y1, x2, y2), s in zip(boxes, scores):
                x1, y1, x2, y2 = map(int, [x1, y1, x2, y2])
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, f"{s:.2f}", (x1, max(0, y1 - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

            cv2.imshow("SCRFD (TensorRT EP) - RealSense", frame)
            if (cv2.waitKey(1) & 0xFF) == 27:  # ESC
                break
    finally:
        pipeline.stop()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()