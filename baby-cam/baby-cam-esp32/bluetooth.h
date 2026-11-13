#include <mbedtls/gcm.h>
#include <mbedtls/base64.h>
#include <esp_system.h>

#ifndef BLE_DEF

#define BLE_DEF

// == == == == == == == == == == == == == == == == == == == == == == == == == == == == == ==
// AES-256-GCM ENCRYPTION
// ============================================================

bool getAESKey(uint8_t key[32])
{

    if (strlen(AES_KEY_HEX) != 64)
        return false;

    for (int i = 0; i < 32; i++)
    {

        char hex[3];

        hex[0] = AES_KEY_HEX[i * 2];
        hex[1] = AES_KEY_HEX[i * 2 + 1];
        hex[2] = '\0';

        char *endPtr;

        unsigned long value = strtoul(
            hex, &endPtr, 16);

        if (*endPtr != '\0')
            return false;

        key[i] = (uint8_t)value;
    }

    return true;
}

// Find the password for the currently connected SSID
String getConnectedPassword()
{

    String connectedSSID = WiFi.SSID();

    for (const auto &network : networks)
    {

        if (network.ssid == connectedSSID)
        {
            return network.password;
        }
    }

    return "";
}

bool encryptJSON(const String &json,
                 String &encryptedResult)
{

    uint8_t key[32];

    if (!getAESKey(key))
    {
        D_println("Invalid AES key");
        return false;
    }

    size_t plainLength = json.length();

    // Generate random 96-bit nonce

    uint8_t nonce[NONCE_SIZE];

    esp_fill_random(nonce, NONCE_SIZE);

    // Allocate ciphertext

    std::vector<uint8_t> ciphertext(plainLength);

    uint8_t tag[TAG_SIZE];

    mbedtls_gcm_context ctx;

    mbedtls_gcm_init(&ctx);

    int result = mbedtls_gcm_setkey(
        &ctx,
        MBEDTLS_CIPHER_ID_AES,
        key,
        256);

    if (result != 0)
    {

        mbedtls_gcm_free(&ctx);

        D_println("AES setkey failed");
        return false;
    }

    result = mbedtls_gcm_crypt_and_tag(
        &ctx,
        MBEDTLS_GCM_ENCRYPT,
        plainLength,
        nonce,
        NONCE_SIZE,
        nullptr,
        0,
        (const uint8_t *)json.c_str(),
        ciphertext.data(),
        TAG_SIZE,
        tag);

    mbedtls_gcm_free(&ctx);

    if (result != 0)
    {

        D_println("AES encryption failed");
        return false;
    }

    // Build binary payload:
    // nonce + ciphertext + authentication tag

    std::vector<uint8_t> payload;

    payload.reserve(
        NONCE_SIZE + plainLength + TAG_SIZE);

    payload.insert(
        payload.end(),
        nonce,
        nonce + NONCE_SIZE);

    payload.insert(
        payload.end(),
        ciphertext.begin(),
        ciphertext.end());

    payload.insert(
        payload.end(),
        tag,
        tag + TAG_SIZE);

    // Base64 encode

    size_t outputLength =
        4 * ((payload.size() + 2) / 3) + 1;

    std::vector<unsigned char> encoded(outputLength);

    size_t actualLength = 0;

    result = mbedtls_base64_encode(
        encoded.data(),
        encoded.size(),
        &actualLength,
        payload.data(),
        payload.size());

    if (result != 0)
    {

        D_println("Base64 encoding failed");
        return false;
    }

    encoded[actualLength] = '\0';

    encryptedResult = String(
        (const char *)encoded.data());

    D_printf("Encrypted string len %d\n", actualLength);

    return true;
}

void set_ble_ip_chara() {
    
    if (ipStatusChar == nullptr) {
        D_println("ipStatus chara not defined");
        return;
    }

    if (WiFi.status() != WL_CONNECTED) {
        ipStatusChar->setValue("NOT CONNECTED");
        return;
    }

    String password = getConnectedPassword();

    if (password.length() == 0 &&
        !WiFi.SSID().isEmpty())
    {

        // An empty password is valid for an open AP.
        // Check whether this SSID is actually in our list.

        bool found = false;

        for (const auto &network : networks)
        {
            if (network.ssid == WiFi.SSID())
            {
                found = true;
                break;
            }
        }

        if (!found)
        {
            D_println("Connected SSID not in credential list");
            return;
        }
    }

    // ============================================================
    // CREATE ENCRYPTED WIFI JSON
    // ============================================================
    JsonDocument doc;

    doc["ap_name"] = WiFi.SSID();
    doc["password"] = password;
    doc["audio_ip"] = WiFi.localIP().toString();

    String json;

    serializeJson(doc, json);

    D_println("Creating encrypted WiFi information");

    String encrypted;

    if (!encryptJSON(json, encrypted))
        D_println("Encrypt failed");
        ipStatusChar->setValue("ENCRYPT FAILED");
        return;

    if (encrypted.length() > 512)
    {
        ipStatusChar->setValue("CHARA TOO LONG");
        D_println("Encrypted BLE data exceeds 512 bytes");
        return;
    }

    // Store encrypted payload in BLE characteristic

    ipStatusChar->setValue(encrypted.c_str());

    D_println("BLE characteristic updated");
}

class ServerCallbacks : public NimBLEServerCallbacks
{
public:

    void onConnect(NimBLEServer* pServer,
                   NimBLEConnInfo& connInfo)
    {
        D_println("BLE client connected");
    }

    void onDisconnect(NimBLEServer* pServer,
                      NimBLEConnInfo& connInfo,
                      int reason)
    {
        D_println("BLE client disconnected");
        NimBLEDevice::startAdvertising();
    }
};


void startBLE() {

    NimBLEDevice::init("BABY-CAM");

    // NimBLEDevice::setPower(ESP_PWR_LVL_P9);

    bleServer = NimBLEDevice::createServer();
    bleServer->setCallbacks(new ServerCallbacks());

    bleService = bleServer->createService(SERVICE_UUID);

    ipStatusChar = bleService->createCharacteristic(
        IP_CHAR_UUID,
        NIMBLE_PROPERTY::READ 
        // |
        // NIMBLE_PROPERTY::NOTIFY    
    );

    set_ble_ip_chara();

    bleService->start();    

    NimBLEAdvertising* advertising =
        NimBLEDevice::getAdvertising();

    advertising->addServiceUUID(bleService->getUUID());
    advertising->setName("BABY-CAM");


    // advertising->setMinInterval(800);
    // advertising->setMaxInterval(1200);
    advertising->start();
    ble_on = true;
    D_println("BLE started");
    ble_on_time = millis();
}

void stopBLE() {
    if (millis() - ble_on_time < BLE_ON_MIN_TIME) {
        //BLE must be on for a little while to prevent crashes
        return;
    }    
    NimBLEAdvertising* advertising =
        NimBLEDevice::getAdvertising();

    if (advertising)
    {
        advertising->stop();
    }

    NimBLEDevice::deinit(true);
    ble_on = false;
    ipStatusChar = nullptr;
    D_println("BLE stopped");
}

//BLE uses the same antenna as Wifi and so we need turn off BLE when we are streaming audio
//We can turn it back on once the audioclient has disconnected.
void checkBLE() {
    if (ble_on && (audioClients > 0 || configAPActive)) {
        //If we have an audioclient or we are in SoftAP mode, turn off BLE 
        stopBLE();
    } else if (!ble_on && audioClients == 0 && !configAPActive ) {
        //No audio clients and we are not in SoftAP mode, so start advertising again
        startBLE();
    }
}

void notifyIPChange() {
    if (ble_on) {
        set_ble_ip_chara();
    }
    // ipStatusChar->notify();    
}

#endif