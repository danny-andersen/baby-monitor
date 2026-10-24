#include <Arduino.h>
#include <WiFi.h>
#include <WiFiMulti.h>

#include "wifi-defs.h"
#include "baby-cam-defs.h"
#include "wifiStatus.h"
#include "bluetooth.h"
#include "serial_comms.h"
#include "audio.h"
#include "batt_volt_sense.h"
#include "infra_red_driver.h"


// -------------------------
// Setup
// -------------------------
void setup()
{
    D_SerialBegin(115200);
    delay(1000);
    unsigned long start = millis();
    while (!Serial && (millis() - start) < 3000) {
     vTaskDelay(pdMS_TO_TICKS(10));
    }
    D_println("Setup start");

    power_setup();
    setupInfraDriver();

    setupWifi();
    setupBluetooth();
    setupStatusWebServer();
    setupI2S();
    setupAudioServer();
    setupPiSerialComms();
    D_println("Set up complete");
}

// -------------------------
// Main loop
// -------------------------
void loop()
{
    check_wifi();
    // Check on power situation
    power_control();
    driveInfraLight();
    server.handleClient();
    requestPiStatus();  //Send regular status check to PI
    if (last_req_time > 0) {
        checkPiResponse();  //Check for any comms from PI
    }
    vTaskDelay(pdMS_TO_TICKS(10));
    // D_printf("Batttery perc: %f\n", batt_percentage);
    // delay(1000);
}