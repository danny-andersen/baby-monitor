#define DEBUG 1 // SET TO 0 TO REMOVE TRACES

#if DEBUG
#define D_SerialBegin(...) Serial.begin(__VA_ARGS__)
#define D_print(...) Serial.print(__VA_ARGS__)
#define D_write(...) Serial.write(__VA_ARGS__)
#define D_println(...) Serial.println(__VA_ARGS__)
#define D_printf(...) Serial.printf(__VA_ARGS__)
#else
#define D_SerialBegin(...)
#define D_print(...)
#define D_write(...)
#define D_println(...)
#define D_printf(...)
#endif

// General Pins
#define CURRENT_DRAIN_PIN 3 // Keeps the battery protection from turning off the power when only the ESP is running
#define BATT_VOLTAGE_PIN 6
#define PI_POWER_PIN 14 // Controls power to PI via a relay: low is on, high is off


void setup() {
    D_SerialBegin(115200);
    delay(1000);

    //Set up output for transistor to act as a current drain to stop battery protection circuit from turning off the power
    //Also used as a power on indicator
    pinMode(CURRENT_DRAIN_PIN, OUTPUT);
    digitalWrite(CURRENT_DRAIN_PIN, 1);

    // pinMode(PI_POWER_STATE_PIN, OUTPUT);
    // digitalWrite(CURRENT_DRAIN_PIN, 1);

    pinMode(PI_POWER_PIN, OUTPUT);
    digitalWrite(PI_POWER_PIN, 1);

}

void loop() {
  //Turn PI on, as battery voltage sufficient (low transition is on)
  D_println("Turning output on");
  digitalWrite(PI_POWER_PIN, 1);
  delay(3000);
  D_println("Turning output off");
  digitalWrite(PI_POWER_PIN, 0);
  delay(3000);
}
