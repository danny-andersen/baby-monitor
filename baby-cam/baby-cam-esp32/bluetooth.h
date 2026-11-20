#include <psa/crypto.h>
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

// ============================================================
// BASE64 ENCODING
// ============================================================

String base64Encode(const uint8_t* data, size_t length) {

    static const char table[] =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "abcdefghijklmnopqrstuvwxyz"
        "0123456789+/";

    String output;
    output.reserve(((length + 2) / 3) * 4);

    for (size_t i = 0; i < length; i += 3) {

        uint32_t value =
            (uint32_t)data[i] << 16;

        if (i + 1 < length)
            value |= (uint32_t)data[i + 1] << 8;

        if (i + 2 < length)
            value |= data[i + 2];

        output += table[(value >> 18) & 0x3F];
        output += table[(value >> 12) & 0x3F];

        output += (i + 1 < length)
            ? table[(value >> 6) & 0x3F] : '=';

        output += (i + 2 < length)
            ? table[value & 0x3F] : '=';
    }

    return output;
}


// ============================================================
// AES-256-GCM ENCRYPTION USING PSA CRYPTO
// ============================================================

bool encryptJSON(const String& json,
                 String& encryptedResult) {

    uint8_t key[32];

    if (!getAESKey(key)) {
        Serial.println("Invalid AES key");
        return false;
    }

    // Initialise PSA Crypto

    psa_status_t status = psa_crypto_init();

    if (status != PSA_SUCCESS) {
        Serial.printf("PSA init failed: %d\n", status);
        return false;
    }

    // Create a random 96-bit nonce

    uint8_t nonce[NONCE_SIZE];

    esp_fill_random(nonce, NONCE_SIZE);

    // Configure AES-256-GCM key

    psa_key_attributes_t attributes =
        PSA_KEY_ATTRIBUTES_INIT;

    psa_set_key_type(
        &attributes,
        PSA_KEY_TYPE_AES
    );

    psa_set_key_bits(
        &attributes,
        256
    );

    psa_set_key_usage_flags(
        &attributes,
        PSA_KEY_USAGE_ENCRYPT
    );

    psa_set_key_algorithm(
        &attributes,
        PSA_ALG_GCM
    );

    psa_key_id_t keyId;

    status = psa_import_key(
        &attributes,
        key,
        sizeof(key),
        &keyId
    );

    psa_reset_key_attributes(&attributes);

    if (status != PSA_SUCCESS) {
        Serial.printf("PSA key import failed: %d\n", status);
        return false;
    }

    // PSA GCM output is ciphertext followed by tag

    size_t plainLength = json.length();

    std::vector<uint8_t> ciphertext(
        plainLength + TAG_SIZE
    );

    size_t ciphertextLength = 0;

    status = psa_aead_encrypt(
        keyId,
        PSA_ALG_GCM,
        nonce,
        NONCE_SIZE,
        nullptr,                 // No additional data
        0,
        (const uint8_t*)json.c_str(),
        plainLength,
        ciphertext.data(),
        ciphertext.size(),
        &ciphertextLength
    );

    // Destroy temporary key

    psa_destroy_key(keyId);

    if (status != PSA_SUCCESS) {
        Serial.printf("AES-GCM encryption failed: %d\n", status);
        return false;
    }

    // Build payload:
    //
    // nonce (12 bytes)
    // ciphertext (variable)
    // authentication tag (16 bytes)
    //
    // PSA already returns ciphertext + tag together.

    std::vector<uint8_t> payload;

    payload.reserve(
        NONCE_SIZE + ciphertextLength
    );

    payload.insert(
        payload.end(),
        nonce,
        nonce + NONCE_SIZE
    );

    payload.insert(
        payload.end(),
        ciphertext.begin(),
        ciphertext.begin() + ciphertextLength
    );

    // Base64 encode

    encryptedResult = base64Encode(
        payload.data(),
        payload.size()
    );

    Serial.printf(
        "Encrypted JSON: %d bytes, Base64: %d bytes\n",
        payload.size(),
        encryptedResult.length()
    );

    return true;
}

String getWifiCreds() {
    String password = getConnectedPassword();

    if (password.length() == 0 &&
        !WiFi.SSID().isEmpty())
    {
        // An empty password is valid for an open AP.
        // Check whether this SSID is actually in our list.
        bool found = false;
        for (const auto &network : networks) {
            if (network.ssid == WiFi.SSID())
            {
                found = true;
                break;
            }
        }
        if (!found)
        {
            D_println("Connected SSID not in credential list");
            return "";
        }
    }

    // ============================================================
    // CREATE ENCRYPTED WIFI JSON
    // ============================================================
    JsonDocument doc;

    doc["ssid"] = WiFi.SSID();
    doc["password"] = password;
    doc["ip"] = WiFi.localIP().toString();

    String json;

    serializeJson(doc, json);

    D_println("Creating encrypted WiFi information");

    String encrypted;

    if (!encryptJSON(json, encrypted)) {
        D_println("Encrypt failed");
        ipStatusChar->setValue("ENCRYPT FAILED");
        return "";
    }

    if (encrypted.length() > 512)
    {
        ipStatusChar->setValue("CHARA TOO LONG");
        D_println("Encrypted BLE data exceeds 512 bytes");
        return "";
    }
    return encrypted;
}

void set_ble_ip_chara() {
    
    if (ipStatusChar == nullptr) {
        D_println("ipStatus chara not defined");
        return;
    }

    String encrypted = getWifiCreds();

    // Store encrypted payload in BLE characteristic

    ipStatusChar->setValue(encrypted.c_str());

    D_printf("Characteristic stored length: %d\n",
              ipStatusChar->getValue().size());    

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
        NimBLEExtAdvertising* pAdvertising =
            NimBLEDevice::getAdvertising();
        if (pAdvertising) {
            if (!pAdvertising->isActive(0)) {
                D_println("Restarting advertising after disconnect");
                pAdvertising->start(0, 0, 0);
            }
        }
    }
};


void startBLE() {
    if (WiFi.status() != WL_CONNECTED) {
        D_println("Wifi not connected, so BLE not started");
        return;
    }

    NimBLEDevice::init(BLE_DEVICE_NAME);

    D_printf("BLE MAC Address %s\n", NimBLEDevice::getAddress().toString().c_str());
    //  // Request a larger MTU for GATT transfers
    NimBLEDevice::setMTU(517);

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

    Serial.println("Starting GATT service...");

    bool serviceStarted = bleService->start();

    Serial.print("GATT service start result: ");
    Serial.println(serviceStarted ? "SUCCESS" : "FAILED");

    // ---------------------------------------
    // Configure extended advertising
    // ---------------------------------------

    NimBLEExtAdvertisement advertisement;

    // Advertise the device name
    advertisement.setName(BLE_DEVICE_NAME);

    // Advertise the service UUID
    // advertisement.addServiceUUID(NimBLEUUID(SERVICE_UUID));
    advertisement.setLegacyAdvertising(true);
    advertisement.setConnectable(true);

    // Scan response: service UUID
    NimBLEExtAdvertisement scanResponse;

    scanResponse.addServiceUUID(NimBLEUUID(SERVICE_UUID));

    // Get extended advertising manager
    NimBLEExtAdvertising* pAdvertising =
        NimBLEDevice::getAdvertising();

    // Register advertisement data as instance 0
    if (!pAdvertising->setInstanceData(0, advertisement)) {
        D_println("ERROR: Failed to configure BLE advertising");
        return;
    }
    if (!pAdvertising->setScanResponseData(0, scanResponse)) {
        D_println("ERROR: Failed to configure BLE scan response");
        return;
    }
    // Start advertising instance 0 indefinitely
    if (!pAdvertising->start(0, 0, 0)) {
        D_println("ERROR: Failed to start BLE advertising");
        return;
    }

    D_printf("Advertising active: %s\n", pAdvertising->isActive(0) ? "YES" : "NO");

    ble_on = true;
    D_println("BLE started");
    ble_on_time = millis();
}

void stopBLE() {
    if (millis() - ble_on_time < BLE_ON_MIN_TIME) {
        //BLE must be on for a little while to prevent crashes
        return;
    }    
    D_println("Stopping BLE");
    // Stop extended advertising instance 0
    NimBLEExtAdvertising* advertising =
        NimBLEDevice::getAdvertising();

    if (advertising) {
        if (advertising->isActive(0)) {
            advertising->stop(0);
            Serial.println("BLE advertising stopped");
        }
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