#define DEBUG 0 // SET TO 0 TO REMOVE TRACES

#if DEBUG
#define D_SerialBegin(...) Serial.begin(__VA_ARGS__)
#define D_print(...) Serial.print(__VA_ARGS__)
#define D_write(...) Serial.write(__VA_ARGS__)
#define D_println(...) Serial.println(__VA_ARGS__)
#define D_printf(...) Serial.printf(__VA_ARGS__)
#define D_flush() Serial.flush()
#else
#define D_SerialBegin(...)
#define D_print(...)
#define D_write(...)
#define D_println(...)
#define D_printf(...)
#define D_flush() 
#endif

// UART comms with PI
#define PI_SERIAL Serial1
#define PI_SERIAL_TX_PIN 16
#define PI_SERIAL_RX_PIN 17

// General Pins
#define CURRENT_DRAIN_PIN 3 // Keeps the battery protection from turning off the power when only the ESP is running
#define BATT_VOLTAGE_PIN 6
#define PI_POWER_PIN 14 // Controls power to PI via a relay: low is on, high is off

//Power thresholds
#define VIDEO_ON_THRESHOLD 60
#define VIDEO_OFF_THRESHOLD 35
#define POWER_LOW_THRESHOLD 20

//Deep sleep timings
#define uS_TO_S_FACTOR 1000000ULL /* Conversion factor for micro seconds to seconds */
#define TIME_TO_SLEEP  60          /* Time ESP32 will go to sleep (in seconds) */

#define PI_SHUTDOWN_DELAY 60000  /* Time allowed for PI to shutdown */
#define PI_RESPONSE_TIME 5000 /* Time allowed for PI to respond to a command*/ 

//PI status
enum PiStatus {
  UNKNOWN,
  BOOTING,
  CHECKING,
  NO_RESPONSE,
  UP,
  SHUTDOWN_REQUESTED,
  SHUTTING_DOWN,
  SHUTDOWN
};

int current_batt_perc = 0;  // Currently calculated battery percentage
float current_batt_volts = 0.0;
bool video_power = false; //Video off until PI is powered on
bool mic_power = true; //Mic power is always on until power below low threshold
bool drain_power = false; //Whether the circuit to put an extra power load on is on
enum PiStatus pi_status = UNKNOWN;   //State of PI
unsigned long pi_shutdown_time = 0; //Time the PI responded to the shutdown
unsigned long pi_shutdown_request_time; //Time the PI was told to shutdown
unsigned long last_req_time = 0;  //Time last request was sent
unsigned long last_status_time = 0;  //Time last status command was sent

