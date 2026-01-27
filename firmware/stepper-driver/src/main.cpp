#include <Arduino.h>
#include <ArduinoJson.h>
#include <AccelStepper.h>
#include <TMCStepper.h>
#include <crc.h>
#include <main.h>

SemaphoreHandle_t rxDataMutex;

volatile Command command;

#define EN_PIN_0 38
#define DIR_PIN_0 55
#define STEP_PIN_0 54
#define RMS_CURRENT_0 300
#define MICRO_STEPS_0 8

#define EN_PIN_1 38
#define DIR_PIN_1 55
#define STEP_PIN_1 54
#define RMS_CURRENT_1 300
#define MICRO_STEPS_1 8

#define SERIAL_PORT_0 Serial
#define SERIAL_PORT_1 Serial1

#define R_SENSE 0.11f // Matched to Big Tech Tree TMC2209 v1.3

#define DRIVER_ADDRESS_0 0b00 // TMC2209 Driver address according to MS1 and MS2
#define DRIVER_ADDRESS_1 0b00 // TMC2209 Driver address according to MS1 and MS2

TMC2209Stepper driver0(&SERIAL_PORT_0, R_SENSE, DRIVER_ADDRESS_0);
TMC2209Stepper driver1(&SERIAL_PORT_1, R_SENSE, DRIVER_ADDRESS_1);

AccelStepper stepper0(AccelStepper::DRIVER, STEP_PIN_0, DIR_PIN_0);
AccelStepper stepper1(AccelStepper::DRIVER, STEP_PIN_1, DIR_PIN_1);

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
//
///////////////////////////////////////////////////////////////////////////////

void driverSetup()
{
  pinMode(EN_PIN_0, OUTPUT);
  pinMode(STEP_PIN_0, OUTPUT);
  pinMode(DIR_PIN_0, OUTPUT);
  digitalWrite(EN_PIN_0, LOW);

  pinMode(EN_PIN_1, OUTPUT);
  pinMode(STEP_PIN_1, OUTPUT);
  pinMode(DIR_PIN_1, OUTPUT);
  digitalWrite(EN_PIN_1, LOW);

  SERIAL_PORT_0.begin(115200);
  SERIAL_PORT_1.begin(115200);

  driver0.begin();
  driver0.rms_current(RMS_CURRENT_0);
  driver0.pwm_autoscale(1);
  driver0.microsteps(MICRO_STEPS_0);

  driver1.begin();
  driver1.rms_current(RMS_CURRENT_0);
  driver1.pwm_autoscale(1);
  driver1.microsteps(MICRO_STEPS_0);
}

void steppersSetup()
{
  stepper0.setMaxSpeed(50);
  stepper0.setAcceleration(1000);
  stepper0.setEnablePin(EN_PIN_0);

  stepper1.setMaxSpeed(50);
  stepper1.setAcceleration(1000);
  stepper1.setEnablePin(EN_PIN_1);
}

void steppersEnable()
{
  stepper0.enableOutputs();
  stepper1.enableOutputs();
}

void steppersDisable()
{
  stepper0.disableOutputs();
  stepper1.disableOutputs();
}

///////////////////////////////////////////////////////////////////////////////
// Setup / Entry
///////////////////////////////////////////////////////////////////////////////

void setup()
{
  pinMode(PIN_NEOPIXEL, OUTPUT);

  Serial.begin(115200);

  driverSetup();
  steppersSetup();

  rxDataMutex = xSemaphoreCreateMutex();
  xTaskCreatePinnedToCore(uartRxTask, "UART_RX", 4096, NULL, 2, NULL, 1);
}

///////////////////////////////////////////////////////////////////////////////
// Main Loop
///////////////////////////////////////////////////////////////////////////////

void loop()
{
  processCommand();

  stepper0.run();
  stepper1.run();
}