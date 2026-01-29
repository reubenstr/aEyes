const uint32_t RED = 0x00FF0000; 
const uint32_t GREEN = 0x0000FF00; 
const uint32_t BLUE = 0x000000FF;
const uint32_t OFF = 0x00000000;

#pragma pack(1)
struct Message {
    bool motorEnable;   
    float position0;
    float position1;
};

#pragma pack(1)
struct MessagePacket
{
    Message command; 
    uint16_t crc;     
};
