#include <WebServer.h>

WebServer server(8080);


// -------------------------
// Status page
// -------------------------
void handleRoot()
{
    String json;

    json += "{";
    json += "\"battery_volts\": ";
    json += current_batt_volts;
    json += ",";
    json += "\"battery_perc\": ";
    json += current_batt_perc;
    json += ",";
    json += "\"video\": ";
    json += video_power;
    json += ",";
    json += "\"microphone\": ";
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

void setupStatusWebServer() {
    server.on("/", HTTP_GET, handleRoot);
    server.begin();

    D_println("HTTP server started");

}
