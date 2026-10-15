#define STATUS_STR "STATUS"
#define SHUTTING_DOWN_STR "SHUTTING_DOWN"
#define SHUTDOWN_STR "SHUTDOWN"
#define PI_OK "OK"

void setupPiSerialComms() {
    PI_SERIAL.begin(
        115200,
        SERIAL_8N1,
        PI_SERIAL_RX_PIN, // RX pin
        PI_SERIAL_TX_PIN  // TX pin
    );
}

void requestPiStatus() {
  if (pi_status == UNKNOWN || pi_status == UP || pi_status == BOOTING || pi_status == NO_RESPONSE) {
    unsigned long currentMillis = millis();
    if (currentMillis - last_status_time > 10000)
    {
        pi_status = CHECKING;
        last_req_time = currentMillis;
        last_status_time = currentMillis;
        PI_SERIAL.println(STATUS_STR);
    }
    D_println(pi_status_str());
  }
}

void checkPiResponse() {
  unsigned long currentMillis = millis();
  while (PI_SERIAL.available())
  {
      last_req_time = currentMillis;
      String response = PI_SERIAL.readStringUntil('\n');
      response.trim();
      D_print("PI replied: ");
      D_println(response);

      if (response.indexOf(PI_OK) >= 0) {
        D_println("PI is up");
        pi_status = UP;
      }
      if (response.indexOf(SHUTTING_DOWN_STR) >= 0) {
        pi_shutdown_time = currentMillis;
        pi_status = SHUTTING_DOWN;
        D_println("PI is shutting down");
      }
      vTaskDelay(pdMS_TO_TICKS(10));
  }  
  if ((pi_status != NO_RESPONSE || pi_status == BOOTING) && currentMillis - last_req_time > PI_RESPONSE_TIME) 
  {
    pi_status = NO_RESPONSE;
    D_println("PI did not respond");
  }
}

void shutdown_pi() {
  if (pi_shutdown_request_time == 0 || millis() - pi_shutdown_request_time > PI_RESPONSE_TIME) {
      PI_SERIAL.println(SHUTDOWN_STR);
      pi_status = SHUTDOWN_REQUESTED;
      pi_shutdown_request_time = millis();
      last_req_time = millis();
      D_println("PI shutdown request sent");
  }
}

String pi_status_str() {
  String status_str = "";
  switch(pi_status) {
    case UNKNOWN:
      status_str = "UNKNOWN";
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
