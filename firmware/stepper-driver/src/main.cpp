#include <Arduino.h>
#include <ArduinoJson.h>
#include <AccelStepper.h>
#include <TMCStepper.h>
#include <crc.h>
#include <main.h>

SemaphoreHandle_t rxDataMutex;
volatile Message message;
volatile bool newMessageFlag;

#define EN_PIN_0 12
#define DIR_PIN_0 8
#define STEP_PIN_0 9
#define DIAG_PIN_0 13
#define PDN_TX_PIN_0 11
#define PDN_RX_PIN_0 10
#define RMS_CURRENT_0 300
#define MICRO_STEPS_0 8
#define STEPS_PER_REVOLUTION_0 200
#define STEPS_PER_DEGREE_0 (STEPS_PER_REVOLUTION_0 * MICRO_STEPS_0) / 360.0f
#define DRIVER_SERIAL_PORT_0 Serial1

#define EN_PIN_1 5
#define DIR_PIN_1 1
#define STEP_PIN_1 2
#define DIAG_PIN_1 6
#define PDN_TX_PIN_1 4
#define PDN_RX_PIN_1 3
#define RMS_CURRENT_1 300
#define MICRO_STEPS_1 8
#define STEPS_PER_REVOLUTION_1 200
#define STEPS_PER_DEGREE_1 (STEPS_PER_REVOLUTION_1 * MICRO_STEPS_1) / 360.0f
#define DRIVER_SERIAL_PORT_1 Serial2

#define COMMAND_SERIAL_TX_PIN 20
#define COMMAND_SERIAL_RX_PIN 21
#define COMMAND_SERIAL_PORT Serial

#define R_SENSE 0.11f // Matched to Big Tech Tree TMC2209 v1.3

#define DRIVER_ADDRESS_0 0b00 // TMC2209 Driver address according to MS1 and MS2
#define DRIVER_ADDRESS_1 0b00 // TMC2209 Driver address according to MS1 and MS2

TMC2209Stepper driver0(&DRIVER_SERIAL_PORT_0, R_SENSE, DRIVER_ADDRESS_0);
TMC2209Stepper driver1(&DRIVER_SERIAL_PORT_1, R_SENSE, DRIVER_ADDRESS_1);

AccelStepper stepper0(AccelStepper::DRIVER, STEP_PIN_0, DIR_PIN_0);
AccelStepper stepper1(AccelStepper::DRIVER, STEP_PIN_1, DIR_PIN_1);

bool motorsEnabled{false};

const float minAngleDeg0{-45.0};
const float maxAngleDeg0{45.0};
const float minAngleDeg1{-45.0};
const float maxAngleDeg1{45.0};

const float homedAngleDeg0{45};
const float homedAngleDeg1{45};

bool isHoming{false};
bool stepperHomed0{false};
bool stepperHomed1{false};

///////////////////////////////////////////////////////////////////////////////
// Stepper Interfaces
///////////////////////////////////////////////////////////////////////////////

void driverSetup()
{
  pinMode(EN_PIN_0, OUTPUT);
  pinMode(STEP_PIN_0, OUTPUT);
  pinMode(DIR_PIN_0, OUTPUT);
  pinMode(DIAG_PIN_0, INPUT);
  digitalWrite(EN_PIN_0, LOW);

  pinMode(EN_PIN_1, OUTPUT);
  pinMode(STEP_PIN_1, OUTPUT);
  pinMode(DIR_PIN_1, OUTPUT);
  pinMode(DIAG_PIN_1, INPUT);
  digitalWrite(EN_PIN_1, LOW);

  DRIVER_SERIAL_PORT_0.begin(115200, SERIAL_8N1, PDN_RX_PIN_0, PDN_TX_PIN_0);
  DRIVER_SERIAL_PORT_1.begin(115200, SERIAL_8N1, PDN_RX_PIN_1, PDN_TX_PIN_1);

  driver0.begin();
  driver0.rms_current(RMS_CURRENT_0);
  driver0.pwm_autoscale(1);
  driver0.microsteps(MICRO_STEPS_0);

  driver1.begin();
  driver1.rms_current(RMS_CURRENT_1);
  driver1.pwm_autoscale(1);
  driver1.microsteps(MICRO_STEPS_1);
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

void startHoming()
{
  stepperHomed0 = false;
  stepper0.moveTo(homedAngleDeg0 * 2);

  stepperHomed1 = false;
  stepper1.moveTo(homedAngleDeg1 * 2);

  // TODO: set registers?
}

void checkHoming()
{

  if (digitalRead(DIAG_PIN_0))
  {
    stepperHomed0 = true;
    stepper0.stop();
    stepper0.setCurrentPosition(long(homedAngleDeg0 * STEPS_PER_DEGREE_0));
    // TODO clear registers
  }

  if (digitalRead(DIAG_PIN_1))
  {
    stepperHomed1 = true;
    stepper1.stop();
    stepper1.setCurrentPosition(long(homedAngleDeg1 * STEPS_PER_DEGREE_1));
    // TODO clear registers
  }

  if (stepperHomed0 && stepperHomed1)
  {
    isHoming = false;
  }
}

///////////////////////////////////////////////////////////////////////////////
// UART Task
///////////////////////////////////////////////////////////////////////////////

void uartRxTask(void *pvParameters)
{
  const int rxTimeoutMs{20};
  const size_t expectedPacketSize = sizeof(MessagePacket);

  uint8_t buffer[sizeof(MessagePacket)];
  size_t bufferIndex = 0;
  TickType_t lastByteTime = xTaskGetTickCount();

  while (true)
  {
    while (COMMAND_SERIAL_PORT.available())
    {
      uint8_t byte = COMMAND_SERIAL_PORT.read();
      buffer[bufferIndex] = byte;
      bufferIndex++;
      lastByteTime = xTaskGetTickCount();

      if (bufferIndex >= expectedPacketSize)
      {
        MessagePacket *packet = (MessagePacket *)buffer;

        uint16_t calculatedCrc = crc16_ccitt((const uint8_t *)&packet->command, sizeof(Message));

        if (calculatedCrc == packet->crc)
        {
          if (xSemaphoreTake(rxDataMutex, pdMS_TO_TICKS(10)) == pdTRUE)
          {
            newMessageFlag = true;
            memcpy((void *)&message, (void *)&packet->command, sizeof(Message));
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
  Message msg;

  if (newMessageFlag)
  {
    if (xSemaphoreTake(rxDataMutex, pdMS_TO_TICKS(10)) == pdTRUE)
    {
      newMessageFlag = false;
      memcpy((void *)&msg, (void *)&message, sizeof(Message));
      xSemaphoreGive(rxDataMutex);
    }

    Serial.println(msg.motorEnable);
    Serial.println(msg.position0);
    Serial.println(msg.position1);

    // ************************************************* HERE *************************************
    return;
    // ************************************************* HERE *************************************

    if (motorsEnabled && !msg.motorEnable)
    {
      steppersDisable();
    }
    else if (!motorsEnabled && msg.motorEnable)
    {
      steppersEnable();
    }
    motorsEnabled = msg.motorEnable;

    if (msg.position0 >= minAngleDeg0 && msg.position0 <= maxAngleDeg0)
    {
      stepper0.moveTo(long(msg.position0 * STEPS_PER_DEGREE_0));
    }

    if (msg.position1 >= minAngleDeg1 && msg.position1 <= maxAngleDeg1)
    {
      stepper1.moveTo(long(msg.position1 * STEPS_PER_DEGREE_1));
    }
  }
}

///////////////////////////////////////////////////////////////////////////////
// Setup / Entry
///////////////////////////////////////////////////////////////////////////////

void setup()
{
  pinMode(PIN_NEOPIXEL, OUTPUT);

  Serial.begin(115200);
  // COMMAND_SERIAL_PORT.begin(115200, SERIAL_8N1, COMMAND_SERIAL_RX_PIN, COMMAND_SERIAL_TX_PIN);

  // driverSetup();
  // steppersSetup();

  rxDataMutex = xSemaphoreCreateMutex();
  xTaskCreatePinnedToCore(uartRxTask, "UART_RX", 4096, NULL, 2, NULL, 1);
}

///////////////////////////////////////////////////////////////////////////////
// Main Loop
///////////////////////////////////////////////////////////////////////////////

void loop()
{
  if (isHoming)
    checkHoming();
  else
    processCommand();

  stepper0.run();
  stepper1.run();
}