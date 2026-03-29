import zmq
import json
from dataclasses import asdict
from typing import Dict
from data_types import ControlMessage
from parameters import params as _params


class Publisher:
    def __init__(
        self,
        address: str = _params.publisher.socket_address,
        port: int = _params.publisher.socket_port,
    ):
        context = zmq.Context()
        self.socket = context.socket(zmq.PUB)
        self.socket.bind(f"tcp://{address}:{port}")

    def send(self, messages: Dict[int, ControlMessage]) -> None:
        payload = {eye_id: asdict(msg) for eye_id, msg in messages.items()}
        self.socket.send_string(json.dumps(payload))
