#include <WiFi.h>

#include "baby-cam-defs.h"
#include "wifi-defs.h"
#include "audio.h"
#include "batt_volt_sense.h"

WebServer server(8080);

// -------------------------
// Status page
// -------------------------
void handleRoot()
{
    String json;

    json += "{";
    json += "battery_volts: ";
    json += current_batt_volts;
    json += ",";
    json += "battery_perc: ";
    json += current_batt_perc;
    json += ",";
    json += "video: ";
    json += video_power;
    json += ",";
    json += "microphone: ";
    json += mic_power;
    // json += ","
    json += "}";

    // html += "<html><body>";
    // html += "<h1>ESP32-C6 Microphone</h1>";
    // html += "<p>SPH0645LM4H</p>";
    // html += "<p>Sample rate: 16000 Hz</p>";
    // html += "<p>Format: 16-bit mono PCM</p>";
    // html += "<p>Batt Percentage:";
    // html += batt_percentage;
    // html += "</p>";
    // html += "<p><a href=\"/audio\">Audio stream</a></p>";
    // html += "</body></html>";
    server.send(200, "text/json", json);
}

// -------------------------
// Setup
// -------------------------
void setup()
{
    D_SerialBegin(115200);
    delay(1000);

    power_setup();

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

    setupI2S();
    setupAudioServer();

    server.on("/", HTTP_GET, handleRoot);

    server.begin();

    D_println("HTTP server started");
}

// -------------------------
// Main loop
// -------------------------
void loop()
{
    // Check on power situation
    power_control();
    server.handleClient();
    vTaskDelay(pdMS_TO_TICKS(10));
    // D_printf("Batttery perc: %f\n", batt_percentage);
    // delay(1000);
}