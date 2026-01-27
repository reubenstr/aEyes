#include <Arduino.h>
#include <ArduinoJson.h>
#include <crc.h>
#include <main.h>

SemaphoreHandle_t rxDataMutex;

volatile Command command;

///////////////////////////////////////////////////////////////////////////////
// UART Task
///////////////////////////////////////////////////////////////////////////////

void uartRxTask(void *pvParameters)
{
  const int rxTimeoutMs{20};
  const size_t expectedPacketSize = sizeof(RxDataPacket);

  uint8_t buffer[sizeof(RxDataPacket)];
  size_t bufferIndex = 0;
  TickType_t lastByteTime = xTaskGetTickCount();

  while (true)
  {
    while (Serial.available())
    {
      uint8_t byte = Serial.read();
      buffer[bufferIndex] = byte;
      bufferIndex++;
      lastByteTime = xTaskGetTickCount();

      if (bufferIndex >= expectedPacketSize)
      {
        RxDataPacket *packet = (RxDataPacket *)buffer;

        uint16_t calculatedCrc = crc16_ccitt((const uint8_t *)&packet->command, sizeof(Command));

        if (calculatedCrc == packet->crc)
        {
          if (xSemaphoreTake(rxDataMutex, pdMS_TO_TICKS(10)) == pdTRUE)
          {
            memcpy((void *)&command, (void *)&packet->command, sizeof(Command));
            xSemaphoreGive(rxDataMutex);
          }
        }

        bufferIndex = 0;
      }
    }

    TickType_t currentTime = xTaskGetTickCount();
    TickType_t elapsedTicks = currentTime - lastByteTime;
    TickType_t timeoutTicks = pdMS_TO_TICKS(rxTimeoutMs);

    if (bufferIndex > 0 && elapsedTicks >= timeoutTicks)
    {
      bufferIndex = 0;
    }

    vTaskDelay(pdMS_TO_TICKS(1));
  }
}

///////////////////////////////////////////////////////////////////////////////
// Process Commands and Data
///////////////////////////////////////////////////////////////////////////////

void processCommand()
{
  Command localCommand;
    
  if (xSemaphoreTake(rxDataMutex, pdMS_TO_TICKS(10)) == pdTRUE)
  {
    memcpy((void *)&localCommand, (void *)&command, sizeof(Command));
    xSemaphoreGive(rxDataMutex);
  }  

  Serial.println(localCommand.enable);
  Serial.println(localCommand.zero);
  Serial.println(localCommand.angleBase);
  Serial.println(localCommand.angleEye);
  Serial.println("------------------------------");
}

///////////////////////////////////////////////////////////////////////////////
// Setup / Entry
///////////////////////////////////////////////////////////////////////////////

void setup()
{
  pinMode(PIN_NEOPIXEL, OUTPUT);

  Serial.begin(115200);

  rxDataMutex = xSemaphoreCreateMutex();

  xTaskCreatePinnedToCore(
      uartRxTask,
      "UART_RX",
      4096,
      NULL,
      2,
      NULL,
      1);
}

///////////////////////////////////////////////////////////////////////////////
// Main Loop
///////////////////////////////////////////////////////////////////////////////

void loop()
{
  delay(500);
  digitalWrite(PIN_NEOPIXEL, HIGH);
  delay(500);
  digitalWrite(PIN_NEOPIXEL, LOW);

  processCommand();
}