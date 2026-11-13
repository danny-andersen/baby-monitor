// -------------------------
// Status page
// -------------------------
void handleStatusRoot()
{
    JsonDocument doc;

    doc["battery_volts"] = current_batt_volts;
    doc["battery_perc"] = current_batt_perc;
    doc["charging"] = charging;
    doc["camera_status"] = pi_status_desc();
    doc["video_addr"] = video_ip;
    doc["video"] = video_power;
    doc["video_sw"] = video_sw;
    doc["microphone"] = mic_power;
    doc["mic_sw"] = mic_sw;
    doc["infrared_led"] = infrared_lights_on;
    doc["light_level"] = light_level;
    doc["ssid"] = WiFi.SSID();
    doc["ip"] = WiFi.localIP().toString();

    String json;

    serializeJson(doc, json);

    server.send(200, "text/json", json);
}

void handleVideoRequest() {
  D_print("Video request: ");
  if (server.hasArg("req")) {
    // Retrieve the value of the "req" argument
    String reqValue = server.arg("req");
    D_printf("req = %s", reqValue);
    if (reqValue == "1") {
      video_on_requested = true;
      server.send(200, "text/plain", "Success: Video power on");
    } 
    else if (reqValue == "0") {
      video_off_requested = true;
      server.send(200, "text/plain", "Success: Video power off");
    } 
    else {
      server.send(400, "text/plain", "Error");
    }
  } 
  else {
    // If the "req" argument is missing entirely
    server.send(400, "text/plain", "Bad Request");
  }
  D_println();
}

void handleServerRoot() {
  if (configAPActive) {
    handleConfigRoot();
  } else {
    handleStatusRoot();
  }
}

void setupStatusWebServer() {
    server.on("/", HTTP_GET, handleStatusRoot);
    server.on("/video", HTTP_GET, handleVideoRequest);
    server.begin();

    D_println("HTTP server started");

}

void wifiClientConnected() {
    notifyIPChange();
    audio_ip = WiFi.localIP().toString();
    D_printf("\nIP address: %s, on AP: %s\n", audio_ip, WiFi.SSID());
    setupStatusWebServer();
    wifi_connected = true;

}

void setupWifi() {
    // Start in station mode
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);

    // Load saved networks into MultiWifi
    loadNetworks();
    //Merge in preconfigured (only done once)
    mergePreconfiguredNetworks();

    WiFi.setSleep(false);
    // Connect to Wifi

    if (connectWiFi(WIFI_TIMEOUT_MS))
    {
      wifiClientConnected();
    }
    else
    {
      // No known AP found - start configuration portal
      startConfigAP();
    }
    //Common root for both modes
    server.on("/", HTTP_GET, handleServerRoot);
    server.onNotFound(handleServerRoot);

}

void check_wifi() {
    if (!configAPActive && millis() - lastWifiCheckMillis > WIFI_CHECK_INTERVAL) {
        D_printf("Heap=%u, RSSI=%d dBm \n", ESP.getFreeHeap(), WiFi.RSSI());
        lastWifiCheckMillis = millis();
        if (wifiMulti.run() == WL_CONNECTED) {
            if (!wifi_connected) {
                //We have restarted Wifi
                wifiClientConnected();
            }
        } else if (wifi_connected) {
            //Lost connection
            D_println("Lost wifi");
            server.close();
            server.stop();
            wifi_connected = false;
        }
    }
}