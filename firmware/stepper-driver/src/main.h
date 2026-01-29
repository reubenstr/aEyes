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