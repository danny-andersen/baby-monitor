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

//---PIN definitions----

// -------------------------
// I2S pins
// -------------------------
#define I2S_BCLK 0
#define I2S_DOUT 1
#define I2S_WS_LRCLK 2

// UART comms with PI
#define PI_SERIAL Serial1
#define PI_SERIAL_TX_PIN 16
#define PI_SERIAL_RX_PIN 17

// General Pins
#define CURRENT_DRAIN_PIN 3 // Keeps the battery protection from turning off the power when only the ESP is running
#define BATT_VOLTAGE_PIN 6
#define PI_POWER_PIN 14 // Controls power to PI via a relay: low is on, high is off
#define CHARGING_PIN 18 //Set high if battery is charging, i.e. on external power

//Power thresholds
#define VIDEO_ON_THRESHOLD 60
#define VIDEO_OFF_THRESHOLD 35
#define POWER_LOW_THRESHOLD 20

//Deep sleep timings
#define uS_TO_S_FACTOR 1000000ULL /* Conversion factor for micro seconds to seconds */
#define TIME_TO_SLEEP  60          /* Time ESP32 will go to sleep (in seconds) */

#define PI_REQUEST_TIME 10000 /* How often to send a status check to the PI */
#define PI_SHUTDOWN_DELAY 60000  /* Time allowed for PI to shutdown */
#define PI_RESPONSE_TIME 5000 /* Time allowed for PI to respond to a command*/ 

//PI status
enum PiStatus {
  UNKNOWN,
  POWERED_OFF,
  BOOTING,
  NO_RESPONSE,
  UP,
  SHUTDOWN_REQUESTED,
  SHUTTING_DOWN,
  SHUTDOWN
};

bool wifi_connected = false; //Whether we have wifi or not
int current_batt_perc = 0;  // Currently calculated battery percentage
float current_batt_volts = 0.0;
bool video_power = false; //Video off until PI is powered on
bool mic_power = true; //Mic power is always on until power below low threshold
int charging = 0; //Whether powered externally or not
bool drain_power = false; //Whether the circuit to put an extra power load on is on
enum PiStatus pi_status = POWERED_OFF;   //State of PI
String camera_status = "Unknown"; //State of camera service running on the PI
unsigned long pi_shutdown_time = 0; //Time the PI responded to the shutdown
unsigned long pi_shutdown_request_time; //Time the PI was told to shutdown
unsigned long last_req_time = 0;  //Time last request was sent
unsigned long last_status_time = 0;  //Time last status command was sent

String pi_status_str() {
  String status_str = "";
  switch(pi_status) {
    case UNKNOWN:
      status_str = "UNKNOWN";
      break;
    case POWERED_OFF:
      status_str = "POWERED_OFF";
      break;
    case BOOTING:
      status_str = "BOOTING";
      break;
    case NO_RESPONSE:
      status_str = "NO_RESPONSE";
      break;
    case UP:
      status_str = "UP";
      break;
    case SHUTDOWN_REQUESTED:
      status_str = "SHUTDOWN_REQUESTED";
      break;
    case SHUTTING_DOWN:
      status_str = "SHUTTING_DOWN";
      break;
    case SHUTDOWN:
      status_str = "SHUTDOWN";
      break;
  }
  return status_str;
}

String pi_status_desc() {
  String status_str = "";
  switch(pi_status) {
    case UNKNOWN:
    case POWERED_OFF:
      status_str = "\"powered off\"";
      break;
    case BOOTING:
      status_str = "\"starting up\"";
      break;
    case NO_RESPONSE:
      status_str = "\"temporarily unavailable\"";
      break;
    case UP:
      if (camera_status != "") {
        status_str = "\"" + camera_status + "\"";
      }
      else {
        status_str = "\"available\"";
      }
      break;
    case SHUTTING_DOWN:
    case SHUTDOWN_REQUESTED:
      status_str = "\"stopping\"";
      break;
    case SHUTDOWN:
      status_str = "\"powered off\"";
      break;
  }
  return status_str;
}

