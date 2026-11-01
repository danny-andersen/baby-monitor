#include <NimBLEDevice.h>

NimBLECharacteristic* pStatusChar = nullptr;
NimBLEServer* bleServer = nullptr;
NimBLEService* bleService = nullptr;
NimBLECharacteristic* ipStatusChar = nullptr;

bool ble_on = false;
#define BLE_ON_MIN_TIME 30000 //BLE minimum on time 
uint32_t ble_on_time = 0; //Ensure BLE is turned on for a period, otherwise it causes a core dump

void set_ip_chara() {
  String json = "{";
  json += "\"ap_name\": \"";
  json += ap_name;
  json += "\",";
  json += "\"audio_ip\": \"";
  json += audio_ip;
  json += "\"";
  json += "}";
  ipStatusChar->setValue(json);
}

class ServerCallbacks : public NimBLEServerCallbacks
{
public:

    void onConnect(NimBLEServer* pServer,
                   NimBLEConnInfo& connInfo)
    {
        Serial.println("BLE client connected");
    }

    void onDisconnect(NimBLEServer* pServer,
                      NimBLEConnInfo& connInfo,
                      int reason)
    {
        Serial.println("BLE client disconnected");

        // NimBLEDevice::startAdvertising();
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

    set_ip_chara();

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
    D_println("BLE stopped");
}

//BLE uses the same antenna as Wifi and so we need turn off BLE when we are streaming audio
//We can turn it back on once the audioclient has disconnected.
void checkBLE() {
    if (ble_on && audioClients > 0) {
        //If we have an audioclient, turn off BLE 
        stopBLE();
    } else if (!ble_on && audioClients == 0) {
        //No audio clients so start advertising again
        startBLE();
    }
}

void notifyIPChange() {
    set_ip_chara();
    // ipStatusChar->notify();    
}