import os
import depthai as dai
from pathlib import Path
from depthai_nodes.node import ParsingNeuralNetwork, ImgFrameOverlay, ApplyColormap

'''
    https://models.luxonis.com/

'''


MODEL = "luxonis/yunet:640x480"
MODEL_ARCHIVE = "./camera/models/yunet-s-480x640.rvc2.tar.xz"
FPS_LIMIT = 15

cwd = os.getcwd()
print("WORKING DIRECTORY: ", cwd)

visualizer = dai.RemoteConnection(httpPort=8082)
device = dai.Device(dai.DeviceInfo())

platform = device.getPlatformAsString()
print(f"Platform: {platform}")

with dai.Pipeline(device) as pipeline:
    print("Creating pipeline...")

    # model
  
    # Get from Luxonis zoo
    # model_description = dai.NNModelDescription(MODEL, platform=platform)
    # print(model_description)    
    # nn_archive = dai.NNArchive(dai.getModelFromZoo(model_description))

    # Get model from local disk
    nn_archive = dai.NNArchive(Path(MODEL_ARCHIVE))
    
    # media/camera input

    cam = pipeline.create(dai.node.Camera)
    input_node = cam.build()

    nn_with_parser = pipeline.create(ParsingNeuralNetwork).build(
        input_node, nn_archive, fps=FPS_LIMIT
    )
   
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