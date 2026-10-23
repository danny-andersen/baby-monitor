
unsigned long previousLDRMillis = 0;
const long ldrInterval = 10000; // Interval of 10 second

//To give light intensity of 100 at 0.5V and 0 at 3.0V, then y = mx + c with the following:
const float m = -40.0;
const float c = 120.0;

void setupInfraDriver() {
  //Light detector as analogue in
  //Do a dummy reading
  analogRead(DARK_DET_PIN);

  //LED driver
  pinMode(INFRARED_LED_DRIVER, OUTPUT);
  digitalWrite(INFRARED_LED_DRIVER, 0);
}

void driveInfraLight() {
    unsigned long currentMillis = millis();

    // Check if 1 second has elapsed
    if (currentMillis - previousLDRMillis >= ldrInterval)
    {
        previousLDRMillis = currentMillis;
        //Read light level based on input voltage - 0.2V very bright, 2V average 2.9V very dark
        float ldr_volts = analogReadMilliVolts(DARK_DET_PIN) /1000.0;
        light_level = int((ldr_volts * m) + c);
        D_printf("AI %d, Light volts: %f, level = %d\n", det_in, ldr_volts, light_level);
        if (video_power && !infrared_lights_on && light_level <= INFRARED_ON_THRESHOLD) {
          digitalWrite(INFRARED_LED_DRIVER, 1);
          infrared_lights_on = true;
          D_println("Turning Infra red lights ON");
        } else if (infrared_lights_on && (!video_power || light_level >= INFRARED_OFF_THRESHOLD)) {
          digitalWrite(INFRARED_LED_DRIVER, 0);
          D_println("Turning Infra red lights OFF");
          infrared_lights_on = false;
        }
    }
}