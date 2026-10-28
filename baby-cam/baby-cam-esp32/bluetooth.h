#include <NimBLEDevice.h>

NimBLECharacteristic* pStatusChar = nullptr;
NimBLEServer* bleServer = nullptr;
NimBLEService* bleService = nullptr;
NimBLECharacteristic* ipStatusChar = nullptr;

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


void setupBluetooth() {

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
}

void notifyIPChange() {
    set_ip_chara();
    // ipStatusChar->notify();    
}