#include <WiFi.h>

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

    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    D_print("Connecting to WiFi");

    while (WiFi.status() != WL_CONNECTED)
    {
        delay(500);
        D_print(".");
    }

    D_println();
    D_print("IP address: ");
    D_println(WiFi.localIP());

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
    // Check on power situation
    power_control();
    server.handleClient();
    requestPiStatus();  //Send regular status check to PI
    checkPiResponse();  //Check for any comms from PI
    vTaskDelay(pdMS_TO_TICKS(10));
    // D_printf("Batttery perc: %f\n", batt_percentage);
    // delay(1000);
}