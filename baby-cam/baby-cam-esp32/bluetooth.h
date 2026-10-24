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
  json += "\",";
  json += "\"video_ip\": \"";
  json += video_ip;
  json += "\"";
  json += "}";
  ipStatusChar->setValue(json);
}

void setupBluetooth() {

    NimBLEDevice::init("BABY-CAM");

    NimBLEDevice::setPower(ESP_PWR_LVL_P9);

    bleServer = NimBLEDevice::createServer();

    bleService = bleServer->createService(SERVICE_UUID);

    ipStatusChar = bleService->createCharacteristic(
        IP_CHAR_UUID,
        NIMBLE_PROPERTY::READ |
        NIMBLE_PROPERTY::NOTIFY    
    );

    set_ip_chara();

    bleService->start();

    NimBLEAdvertising* advertising =
        NimBLEDevice::getAdvertising();

    advertising->addServiceUUID(bleService->getUUID());

    advertising->start();
}

