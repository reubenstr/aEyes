#pragma pack(1)
struct Command {
    bool enable;
    bool zero;
    float angleBase;
    float angleEye;
};

#pragma pack(1)
struct RxDataPacket {
    Command command; 
    uint16_t crc;     
};