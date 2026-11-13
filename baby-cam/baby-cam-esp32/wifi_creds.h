#include <Preferences.h>

#ifndef BLE_DEF
#include "bluetooth.h"
#endif

Preferences preferences;

// ============================================================
// CREDENTIAL STORAGE
// ============================================================

void saveNetworks()
{

    preferences.begin("wifi-config", false);

    preferences.putUChar("count",
                         (uint8_t)networks.size());

    for (size_t i = 0; i < networks.size(); i++)
    {

        String ssidKey = "ssid" + String(i);
        String passKey = "pass" + String(i);

        preferences.putString(
            ssidKey.c_str(),
            networks[i].ssid);

        preferences.putString(
            passKey.c_str(),
            networks[i].password);
    }

    preferences.end();
}

// Add or update a network

bool addNetwork(const String &ssid,
                const String &password)
{

    if (ssid.length() == 0 || ssid.length() > 32)
        return false;

    if (password.length() > 63)
        return false;

    for (auto &network : networks)
    {

        if (network.ssid == ssid)
        {

            network.password = password;

            wifiMulti.addAP(
                ssid.c_str(),
                password.c_str());

            saveNetworks();

            return true;
        }
    }

    if (networks.size() >= MAX_NETWORKS)
        return false;

    WiFiCredential credential;

    credential.ssid = ssid;
    credential.password = password;

    networks.push_back(credential);

    wifiMulti.addAP(
        ssid.c_str(),
        password.c_str());

    saveNetworks();

    return true;
}

void mergePreconfiguredNetworks() {

    bool changed = false;

    for (size_t i = 0; i < PRECONFIGURED_WIFI_COUNT; i++) {

        String ssid = PRECONFIGURED_WIFI[i].ssid;
        String password = PRECONFIGURED_WIFI[i].password;

        bool found = false;

        for (const auto& network : networks) {

            if (network.ssid == ssid) {
                found = true;
                if (password != network.password) {
                    //Password has been changed - re-add
                    D_printf("Changing password for AP %s\n", ssid);
                    if (!addNetwork(ssid, password)) {
                        D_println("Failed to change password");
                    }
                }
                break;
            }
        }

        if (!found) {

            if (networks.size() >= MAX_NETWORKS) {
                D_println("Maximum WiFi networks reached");
                break;
            }

            WiFiCredential credential;

            credential.ssid = ssid;
            credential.password = password;

            networks.push_back(credential);

            D_println("Added predefined WiFi: " + ssid);

            changed = true;
        }
    }

    if (changed) {
        saveNetworks();
    }

    // Rebuild WiFiMulti list from the complete network list

    wifiMulti.APlistClean();

    for (const auto& network : networks) {

        wifiMulti.addAP(
            network.ssid.c_str(),
            network.password.c_str()
        );
    }

    D_printf("Total configured WiFi networks: %d\n",
                  networks.size());
}

void loadNetworks()
{

    networks.clear();

    preferences.begin("wifi-config", true);

    uint8_t count = preferences.getUChar("count", 0);

    if (count > MAX_NETWORKS)
        count = MAX_NETWORKS;

    for (uint8_t i = 0; i < count; i++)
    {

        String ssidKey = "ssid" + String(i);
        String passKey = "pass" + String(i);

        String ssid = preferences.getString(
            ssidKey.c_str(), "");

        String password = preferences.getString(
            passKey.c_str(), "");

        if (ssid.length() > 0)
        {

            WiFiCredential credential;

            credential.ssid = ssid;
            credential.password = password;

            networks.push_back(credential);

            wifiMulti.addAP(
                ssid.c_str(),
                password.c_str());

            D_println("Loaded WiFi: " + ssid);
        }
    }

    preferences.end();

    D_printf("Loaded %d WiFi networks\n",
                  networks.size());
}

// ============================================================
// WIFI CONNECTION
// ============================================================

bool connectWiFi(uint32_t timeoutMs)
{

    D_println();
    D_println("Connecting to WiFi...");

    unsigned long startTime = millis();

    while (millis() - startTime < timeoutMs)
    {

        if (wifiMulti.run() == WL_CONNECTED)
        {

            D_println();
            D_println("WiFi connected");

            D_print("SSID: ");
            D_println(WiFi.SSID());

            D_print("IP: ");
            D_println(WiFi.localIP());

            return true;
        }

        delay(250);
    }

    D_println("WiFi connection timeout");

    return false;
}


// ============================================================
// SOFTAP CONFIGURATION WEB PAGE
// ============================================================

const char CONFIG_PAGE[] PROGMEM = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ESP32 WiFi Configuration</title>

<style>
body {
    font-family: Arial, sans-serif;
    background: #20252b;
    color: white;
    margin: 0;
    padding: 25px;
}
.container {
    max-width: 400px;
    margin: auto;
    background: #303840;
    padding: 22px;
    border-radius: 12px;
}
h2 {
    text-align: center;
}
input {
    box-sizing: border-box;
    width: 100%;
    padding: 12px;
    margin: 8px 0 18px;
    border-radius: 5px;
    border: 1px solid #777;
    font-size: 16px;
}
button {
    width: 100%;
    padding: 14px;
    background: #1686dc;
    border: none;
    border-radius: 5px;
    color: white;
    font-size: 17px;
}
.small {
    color: #bbb;
    font-size: 13px;
    text-align: center;
}
</style>
</head>

<body>

<div class="container">

<h2>WiFi Configuration</h2>

<p>Enter the credentials of your WiFi access point.</p>

<form action="/save" method="POST">

<label>Network name (SSID)</label>
<input type="text" name="ssid"
       maxlength="32" required>

<label>WiFi password</label>
<input type="password" name="password"
       maxlength="63">

<button type="submit">Save and Connect</button>

</form>

<p class="small">
ESP32-C6 WiFi provisioning
</p>

</div>

</body>
</html>
)rawliteral";

// ============================================================
// WEB SERVER HANDLERS
// ============================================================

void handleConfigRoot()
{
    D_println("AP Config root page");
    server.send_P(
        200,
        "text/html",
        CONFIG_PAGE);
}

void handleStatus()
{
    D_println("AP Config status page");

    JsonDocument doc;

    doc["connected"] =
        WiFi.status() == WL_CONNECTED;

    doc["ssid"] = WiFi.SSID();

    doc["ip"] = WiFi.localIP().toString();

    doc["networks"] = networks.size();

    String response;

    serializeJson(doc, response);

    server.send(
        200,
        "application/json",
        response);
}

void handleSave()
{
    D_println("AP Config save page");

    if (!server.hasArg("ssid") ||
        !server.hasArg("password"))
    {

        server.send(
            400,
            "text/plain",
            "Missing SSID or password");

        return;
    }

    String ssid = server.arg("ssid");
    String password = server.arg("password");

    ssid.trim();

    if (ssid.length() == 0 ||
        ssid.length() > 32 ||
        password.length() > 63)
    {

        server.send(
            400,
            "text/plain",
            "Invalid credentials");

        return;
    }

    D_println();
    D_println("New WiFi credentials received");

    D_print("SSID: ");
    D_println(ssid);

    if (!addNetwork(ssid, password))
    {

        server.send(
            400,
            "text/plain",
            "Unable to store network");

        return;
    }

    server.send(
        200,
        "text/html",
        "<html><body>"
        "<h2>Credentials saved</h2>"
        "<p>Attempting WiFi connection...</p>"
        "<p>You can close this page.</p>"
        "</body></html>");

    delay(500);

    if (connectWiFi(NEW_WIFI_TIMEOUT_MS))
    {
        // Stop configuration AP after successful connection
        server.close();
        server.stop();
        WiFi.softAPdisconnect(true);
        D_println("Provisioning successful");
        configAPActive = false;
    }
    else
    {

        D_println("New network connection failed");

        // Keep the configuration AP running.
        // The user can enter different credentials.
    }
}

// ============================================================
// START CONFIGURATION ACCESS POINT
// ============================================================

void startConfigAP()
{

    if (configAPActive)
        return;

    D_println();
    D_println("Starting WiFi configuration AP");

    WiFi.mode(WIFI_AP_STA);

    WiFi.softAPConfig(
        AP_IP,
        AP_GATEWAY,
        AP_SUBNET);

    if (!WiFi.softAP(
            AP_SSID,
            AP_PASSWORD))
    {

        D_println("SoftAP startup failed");
        return;
    }

    server.on("/save", HTTP_POST, handleSave);

    server.on("/status", HTTP_GET, handleStatus);

    server.begin();

    configAPActive = true;

    D_println("Configuration AP started");

    D_print("SSID: ");
    D_println(AP_SSID);

    D_print("IP: ");
    D_println(WiFi.softAPIP());
}

