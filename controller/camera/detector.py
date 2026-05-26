


import os
#from dotenv import load_dotenv

import depthai as dai
from depthai_nodes.node import ParsingNeuralNetwork, ImgFrameOverlay, ApplyColormap

from utils.arguments import initialize_argparser
from utils.input import create_input_node

# load_dotenv(override=True)

#_, args = initialize_argparser()

#if args.api_key:
#    os.environ["DEPTHAI_HUB_API_KEY"] = args.api_key

'''
https://models.luxonis.com/

'''


#print(args)

MODEL = "luxonis/yolov6-nano:r2-coco-512x288"
MODEL = "luxonis/yunet:640x480"
MODEL_BLOB = "./camera/models/face-detection-retail-0004_openvino_2021.4_8shave.blob"
MODEL_BLOB = "./camera/models/yolov6n-r2-288x512.rvc2.tar.xz"

cwd = os.getcwd()
print("WORKING DIRECTORY: ", cwd)

visualizer = dai.RemoteConnection(httpPort=8082)

class Args:
    api_key = ""
    device = None
    model = "luxonis/yolov6-nano:r2-coco-512x288"
    fps_limit = 28
    media_path = None
    overlay_mode = False


args = Args()

device = dai.Device(dai.DeviceInfo())


platform = device.getPlatformAsString()
print(f"Platform: {platform}")

with dai.Pipeline(device) as pipeline:
    print("Creating pipeline...")

    # model
  
    model_description = dai.NNModelDescription(MODEL, platform=platform)
    print(model_description)
    
    nn_archive = dai.NNArchive(dai.getModelFromZoo(model_description))
    #nn_archive = dai.NNArchive(MODEL_BLOB)


    # media/camera input
    input_node = create_input_node(
        pipeline,
        platform,
        args.media_path,
    )

    nn_with_parser = pipeline.create(ParsingNeuralNetwork).build(
        input_node, nn_archive, fps=args.fps_limit
    )

    # annotation and visualization
    if args.overlay_mode:
        # transform output array to colormap
        apply_colormap_node = pipeline.create(ApplyColormap).build(nn_with_parser.out)
        # overlay frames
        overlay_frames_node = pipeline.create(ImgFrameOverlay).build(
            nn_with_parser.passthrough,
            apply_colormap_node.out,
        )
        visualizer.addTopic("Video", overlay_frames_node.out, "images")
    else:
        visualizer.addTopic("Video", nn_with_parser.passthrough, "images")
    visualizer.addTopic("Detections", nn_with_parser.out, "images")

    print("Pipeline created.")

    pipeline.start()
    visualizer.registerPipeline(pipeline)

    while pipeline.isRunning():
        key = visualizer.waitKey(1)
        if key == ord("q"):
            print("Got q key from the remote connection!")
            break