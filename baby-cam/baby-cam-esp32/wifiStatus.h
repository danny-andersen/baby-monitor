#include <WebServer.h>

WiFiMulti wifiMulti;

WebServer server(8080);

unsigned long lastWifiCheckMillis = 0;
const long wifi_check_interval = 10000; // Interval of 10 second (1000 ms)

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
    json += "\"camera_status\": ";
    json += pi_status_desc();
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

void setupWifi() {
    // Connect to an available AP
    for (int i=0; i<NO_OF_APS; i++) {
        wifiMulti.addAP(WIFI_AP_ARRAY[i].apName, WIFI_AP_ARRAY[i].apPassword);
    }
    // WiFi.mode(WIFI_STA);
    // WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    D_print("Connecting to WiFi");

    // while (WiFi.status() != WL_CONNECTED)
    // {
    //     delay(500);
    //     D_print(".");
    // }
    // D_println();
    // D_print("IP address: ");
    // D_println(WiFi.localIP());
 

    if (wifiMulti.run() == WL_CONNECTED) {
        wifi_connected = true;
        D_println();
        D_print("IP address: ");
        D_println(WiFi.localIP());
        setupStatusWebServer();
    } 
}

void check_wifi() {
    unsigned long currentMillis = millis();
    if (lastWifiCheckMillis - currentMillis > wifi_check_interval) {
        //If we dont have wifi check to see if it is now up
        lastWifiCheckMillis = currentMillis;
        if (wifiMulti.run() == WL_CONNECTED) {
            if (!wifi_connected) {
                //We have restarted Wifi
                wifi_connected = true;
                D_println();
                D_print("IP address: ");
                D_println(WiFi.localIP());
                setupStatusWebServer();
            }
        } else {
            //Lost connection
            D_println("Lost wifi");
            wifi_connected = false;
        }
    }
}