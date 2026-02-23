import pyrealsense2 as rs

'''
    Barebones camera test.
    Run directly on Jetson (with monitor).
'''

pipeline = rs.pipeline()
config = rs.config()

config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)

pipeline.start(config)

while True:
    frames = pipeline.wait_for_frames()
    depth = frames.get_depth_frame()
    color = frames.get_color_frame()

    if not depth or not color:
        continue

    print("Frames received")

pipeline.stop()