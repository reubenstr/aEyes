import cv2
import torch
import pyrealsense2 as rs
import numpy as np

if not torch.cuda.is_available():
    print("Cuda not available!")
    exit(1)

# Set the device to GPU (cuda) or CPU
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print(f'Using device: {device}')  # Should print 'cuda' if GPU is available


# Initialize RealSense pipeline
pipeline = rs.pipeline()
config = rs.config()
config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)

# Start the pipeline
pipeline.start(config)

# Load the pre-trained YOLOv5 model (for face detection)
#model = torch.hub.load('ultralytics/yolov5', 'yolov5s', pretrained=True)  # 'yolov5s' is the small model
model = torch.hub.load('ultralytics/yolov5', 'yolov5s', pretrained=True, trust_repo=True)

# Function to process YOLOv5 output and draw bounding boxes
def draw_boxes(img, results):
    for *xyxy, conf, cls in results.xyxy[0]:  # For each detected object
        if int(cls) == 0:  # Class 0 is 'person' in YOLOv5 pre-trained models
            x1, y1, x2, y2 = map(int, xyxy)
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)  # Draw bounding box
            centroid = (x1 + x2) // 2, (y1 + y2) // 2
            cv2.circle(img, centroid, 5, (255, 0, 0), -1)  # Draw centroid
            cv2.putText(img, f"Face: {conf:.2f}", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)
    return img

# Main loop to capture frames from RealSense and process them
while True:
    # Wait for a frame from the RealSense camera
    frames = pipeline.wait_for_frames()
    color_frame = frames.get_color_frame()

    # Convert the color frame to a numpy array
    color_image = np.asanyarray(color_frame.get_data())

    # Perform face detection with YOLOv5
    results = model(color_image)

    # Draw bounding boxes and centroids
    processed_image = draw_boxes(color_image, results)

    # Display the image
    cv2.imshow('RealSense YOLOv5 Face Detection', processed_image)

    # Break loop if 'q' is pressed
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Stop the RealSense pipeline and close windows
pipeline.stop()
cv2.destroyAllWindows()