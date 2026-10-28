#define STATUS_STR "<STATUS>"
#define SHUTTING_DOWN_STR "<SHUTTING_DOWN>"
#define SHUTDOWN_STR "<SHUTDOWN>"
#define PI_OK "<OK"
#define CAMERA_STR "CAMERA="
#define GET_IP "<GET_IP>"
#define IP_ADDR "IP="

void setupPiSerialComms() {
    PI_SERIAL.begin(
        115200,
        SERIAL_8N1,
        PI_SERIAL_RX_PIN, // RX pin
        PI_SERIAL_TX_PIN  // TX pin
    );
}

void requestPiStatus() {
  if (video_power && (pi_status == UNKNOWN || pi_status == UP || pi_status == BOOTING || pi_status == NO_RESPONSE)) {
    //Only check PI if we know it is up or should be up
    unsigned long currentMillis = millis();
    if ((currentMillis - last_status_time) > PI_REQUEST_TIME)
    {
      last_req_time = currentMillis;
      last_status_time = currentMillis;
      PI_SERIAL.println(STATUS_STR);
    }
  }
}

void requestPiAddr() {
  unsigned long currentMillis = millis();
  last_req_time = currentMillis;
  last_status_time = currentMillis;
  PI_SERIAL.println(GET_IP);
}

void checkPiResponse() {
  unsigned long currentMillis = millis();
  static String rxLine;
  while (PI_SERIAL.available())
  {
    char c = PI_SERIAL.read();

    if (c == '\n')
    {
        rxLine.trim();

        last_req_time = 0;
 
        D_print("PI replied: ");
        D_println(rxLine);

        if (rxLine.indexOf(PI_OK) >= 0) {
          if (pi_status != UP || video_ip.indexOf("0.0.0.0") >=0 ) {
            //If PI has been down or we dont have an IP address yet, send the request
            request_pi_addr = true;
          }
          pi_status = UP;
          if (rxLine.indexOf(CAMERA_STR) >=0) {
            int startPos = rxLine.indexOf("=")+1;
            int endPos = rxLine.indexOf(">");
            if (startPos >= 0 && endPos >= 0) {
              camera_status = rxLine.substring(startPos, endPos);
            }
          }
        }
        D_printf("Status %d: %s\n", pi_status,pi_status_str());
        int ip_pos = rxLine.indexOf(IP_ADDR);
        if (ip_pos >=0) {
          int startPos = ip_pos + 3;
          int endPos = rxLine.indexOf(">");
          if (startPos >= 0 && endPos >= 0) {
            video_ip = rxLine.substring(startPos, endPos);
            D_printf("Rx PI ip addr %s\n", video_ip);
            notifyIPChange();
          }
        }
        if (rxLine.indexOf(SHUTTING_DOWN_STR) >= 0) {
          pi_shutdown_time = currentMillis;
          pi_status = SHUTTING_DOWN;
          D_println("PI is shutting down");
        }

        rxLine = "";
    }
    else
    {
        rxLine += c;
    }
    vTaskDelay(pdMS_TO_TICKS(10));
  }    

  if (last_req_time > 0 && ((currentMillis - last_req_time) > PI_RESPONSE_TIME)) 
  {
    // A request was sent but has timed out
    D_printf("PI did not respond: %s\n", pi_status_str());
    last_req_time = 0;
    if (pi_status == UP || pi_status == UNKNOWN) 
    {
      pi_status = NO_RESPONSE;
    }
    if (pi_status == SHUTDOWN_REQUESTED) {
      //Start the clock ticking anyway
      pi_shutdown_time = currentMillis;
      //Try sending command again
      pi_shutdown_request_time = 0;
    }
  }
}

void shutdown_pi() {
  if (pi_shutdown_request_time == 0) {
      PI_SERIAL.println(SHUTDOWN_STR);
      pi_status = SHUTDOWN_REQUESTED;
      unsigned long currentMillis = millis();
      pi_shutdown_request_time = currentMillis;
      last_req_time = currentMillis;
      D_println("PI shutdown request sent");
  }
}

