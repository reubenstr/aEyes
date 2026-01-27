import struct

def crc16_ccitt(data: bytes) -> int:
    """Calculate CRC16-CCITT checksum"""
    crc = 0xFFFF
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            crc = (crc << 1) ^ 0x1021 if (crc & 0x8000) else crc << 1
            crc &= 0xFFFF
    return crc

def create_rx_data_packet(enable: bool, zero: bool, angle_base: float, angle_eye: float) -> bytes:
    """Create RxDataPacket with Command payload and CRC"""
    
    command_data = struct.pack('<BBff', 
                               int(enable), 
                               int(zero), 
                               angle_base, 
                               angle_eye)
    
   
    crc = crc16_ccitt(command_data)  
    crc_bytes = struct.pack('<H', crc) 
    packet = command_data + crc_bytes
    
    return packet


if __name__ == "__main__": 
    packet = create_rx_data_packet(True, False, 45.5, 30.2)
    
    print(f"Packet size: {len(packet)} bytes, data: {list(packet)}")

 
    import serial
    ser = serial.Serial('/dev/ttyACM0', 115200)
    ser.write(packet)