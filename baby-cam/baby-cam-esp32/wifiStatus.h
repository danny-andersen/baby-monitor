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
    doc["video_ssid"] = video_ap;
    doc["video"] = video_power;
    doc["video_sw"] = video_sw;
    doc["microphone"] = mic_power;
    doc["mic_sw"] = mic_sw;
    doc["infrared_led"] = infrared_lights_on;
    doc["light_level"] = light_level;
    doc["ssid"] = audio_ap;
    doc["ip"] = audio_ip;
    doc["ble_on"] = ble_on;

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
    audio_ap = WiFi.SSID();
    D_printf("\nIP address: %s, on AP: %s\n", audio_ip, audio_ap);
    setupStatusWebServer();
    wifi_connected = true;
    if (video_ip != "0.0.0.0" && video_ap != audio_ap && !configAPActive) {
      //Tell PI to get with the programme
      requestPISetAP(); 
    }

}

void tryKnownNetwork(const char* ssid, const char* password)
{
    Serial.printf("Attempting connection to %s\n", ssid);

    wifiState = WIFI_CONNECTING;
    connectStartTime = millis();

    // Keep AP running, but use both AP and station mode
    WiFi.mode(WIFI_AP_STA);

    WiFi.begin(ssid, password);
}

void monitorWifiConnection()
{
    if (wifiState != WIFI_CONNECTING)
        return;

    if (WiFi.status() == WL_CONNECTED)
    {
        Serial.printf("Connected to %s\n",
                      WiFi.SSID().c_str());

        Serial.printf("IP address: %s\n",
                      WiFi.localIP().toString().c_str());

        // Connection successful - now shut down SoftAP
        // Stop configuration AP after successful connection
        server.close();
        server.stop();
        WiFi.softAPdisconnect(true);
        configAPActive = false;
        wifiState = WIFI_CONNECTED;
        D_println("SoftAP stopped");
    }
    else if (millis() - connectStartTime > WIFI_TIMEOUT_MS)
    {
        if (connectingNetwork != -1) {
          D_printf("Marking network %d as bad\n", connectingNetwork);
          networkList[connectingNetwork].goodNetwork = false;
        }

        D_println("Connection timed out");
        // Stop the failed station connection
        WiFi.disconnect(false, false);
        // Remain in AP+STA mode
        wifiState = WIFI_AP_MODE;
        startConfigAP();
    }
}

void setupWifi() {
    // Start in station mode
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);

    // Load saved networks into MultiWifi
    loadNetworks();
    //Merge in preconfigured (only done once)
    mergePreconfiguredNetworks();

    D_print("Loaded networks: ");
    for (uint8_t i=0; i<networkCount; i++) {
        D_print(networkList[i].ssid);
    }
    D_println();
    WiFi.setSleep(false);
    // Connect to Wifi

    wifiState = WIFI_CONNECTING;
    if (connectWiFi(WIFI_TIMEOUT_MS))
    {
      wifiState = WIFI_CONNECTED;
      wifiClientConnected();
    }
    else
    {
      // No known AP found - start configuration portal
      wifiState = WIFI_AP_MODE;
      startConfigAP();
    }
    //Common root for both modes
    server.on("/", HTTP_GET, handleServerRoot);
    server.onNotFound(handleServerRoot);

}

void check_wifi() {
    monitorWifiConnection();
    if (millis() - lastWifiCheckMillis > WIFI_CHECK_INTERVAL) {
      D_printf("Heap=%u, Min Heap=%u RSSI=%d dBm \n", ESP.getFreeHeap(), ESP.getMinFreeHeap(), WiFi.RSSI());
      lastWifiCheckMillis = millis();
      if (!configAPActive) {
          // In normal AP client mode - check still connected ok
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
              //Wifi will try and reconnect - give it a chance before going into ConfigAPmode
              wifiState = WIFI_CONNECTING;
              connectStartTime = millis();
          }
      } else {
        //Couldnt connect to a wifi network before, so we are in SoftAP mode - check to see if we can connect now
        D_println("In AP mode - scanning for known networks...");
        int n = WiFi.scanNetworks(false, true);
        if (n < 0)
        {
            D_println("WiFi scan failed");
            return;
        }

        bool knownNetworkFound = false;
        for (int i = 0; i < n; i++)
        {
            String ssid = WiFi.SSID(i);
            D_printf("Found: %s, RSSI: %d\n",
                          ssid,
                          WiFi.RSSI(i));
            // Check against pre-configured networks
            bool found = false;
            for (uint8_t i = 0; i < networkCount; i++) {
              if (ssid.compareTo(networkList[i].ssid) == 0) {
                if (networkList[i].goodNetwork) {
                  knownNetworkFound = true;
                  connectingNetwork = i;
                  D_printf("Trying known good network id %d found: %s\n", i, ssid);
                  tryKnownNetwork(networkList[i].ssid, networkList[i].password);
                  break;
                } else {
                  D_printf("Ignoring known bad network %s\n",ssid);
                }
              }
            }
            if (knownNetworkFound)
                break;
        }
        //Clear bad flag on networks that are not present - they may have failed if the network went down
        for (uint8_t i = 0; i < networkCount; i++) {
          if (!networkList[i].goodNetwork) {
            bool found = false;
            for (int j = 0; j < n; j++)
            {
                String ssid = WiFi.SSID(j);
                if (ssid.compareTo(networkList[i].ssid) == 0) {
                  found = true;
                  break;
                }
            }
            if (!found) {
              networkList[i].goodNetwork = true;
            }
          }
        }
        WiFi.scanDelete();
      }
    }
}