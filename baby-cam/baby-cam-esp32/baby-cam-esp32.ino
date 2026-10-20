#include <Arduino.h>
#include <WiFi.h>
#include <WiFiMulti.h>

#include "wifi-defs.h"
#include "baby-cam-defs.h"
#include "wifiStatus.h"
#include "serial_comms.h"
#include "audio.h"
#include "batt_volt_sense.h"


// -------------------------
// Setup
// -------------------------
void setup()
{
    D_SerialBegin(115200);
    delay(1000);

    setupWifi();
    power_setup();
    setupStatusWebServer();
    setupPiSerialComms();
    setupI2S();
    setupAudioServer();

}

// -------------------------
// Main loop
// -------------------------
void loop()
{
    check_wifi();
    // Check on power situation
    power_control();
    server.handleClient();
    requestPiStatus();  //Send regular status check to PI
    if (last_req_time > 0) {
        checkPiResponse();  //Check for any comms from PI
    }
    vTaskDelay(pdMS_TO_TICKS(10));
    // D_printf("Batttery perc: %f\n", batt_percentage);
    // delay(1000);
}