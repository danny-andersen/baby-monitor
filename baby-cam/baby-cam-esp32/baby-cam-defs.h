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

//Power thresholds
#define VIDEO_ON_THRESHOLD 70
#define VIDEO_OFF_THRESHOLD 40
#define POWER_LOW_THRESHOLD 20

int current_batt_perc = 0;  // Currently calculated battery percentage
float current_batt_volts = 0.0;
bool video_power = 0; //Video off until PI is powered on
bool mic_power = 1; //Mic power is always on until power below low threshold
