import zmq
import time
import json  

context = zmq.Context()
socket = context.socket(zmq.PUB)
socket.bind("tcp://*:5555") 

count = 0
while True:
    msg = {}
    msg['rotation'] = count
   
    msg_str = json.dumps(msg)
    socket.send_string(msg_str)

    print("Sent:", msg)
    count += 1
    time.sleep(0.025)