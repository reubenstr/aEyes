import zmq

context = zmq.Context()
socket = context.socket(zmq.SUB)
socket.connect("tcp://localhost:5555")  

socket.setsockopt_string(zmq.SUBSCRIBE, "")  

while True:
    msg = socket.recv_string()
    print("Received:", msg)