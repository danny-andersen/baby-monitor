// Lookup table for a standard 3.7V LiPo/Li-ion battery (fully charged at 4.2V)
// Index 0 corresponds to 0%, Index 100 corresponds to 100%
// const float lipo_voltage_table[] PROGMEM = {
//     3.20, 3.25, 3.30, 3.35, 3.40, 3.43, 3.46, 3.49, 3.51, 3.53, // 0% - 9%
//     3.55, 3.57, 3.59, 3.60, 3.62, 3.63, 3.65, 3.66, 3.67, 3.68, // 10% - 19%
//     3.69, 3.70, 3.71, 3.72, 3.73, 3.73, 3.74, 3.74, 3.75, 3.75, // 20% - 29%
//     3.76, 3.76, 3.77, 3.77, 3.78, 3.78, 3.78, 3.79, 3.79, 3.79, // 30% - 39%
//     3.80, 3.80, 3.80, 3.81, 3.81, 3.81, 3.82, 3.82, 3.82, 3.83, // 40% - 49%
//     3.83, 3.83, 3.84, 3.84, 3.84, 3.85, 3.85, 3.85, 3.86, 3.86, // 50% - 59%
//     3.87, 3.87, 3.88, 3.88, 3.89, 3.89, 3.90, 3.91, 3.92, 3.92, // 60% - 69%
//     3.93, 3.94, 3.95, 3.95, 3.96, 3.97, 3.98, 3.99, 4.00, 4.01, // 70% - 79%
//     4.02, 4.03, 4.04, 4.05, 4.06, 4.07, 4.08, 4.09, 4.10, 4.11, // 80% - 89%
//     4.12, 4.13, 4.14, 4.15, 4.16, 4.17, 4.17, 4.18, 4.19, 4.20, // 90% - 99%
//     4.20                                                        // 100%
// };

// Lookup table for a standard 3.7V LiPo/Li-ion battery (fully charged at 4.2V)
// Index 0 corresponds to 0%, Index 10 corresponds to 100%
const float lipo_voltage_table[] PROGMEM = {
    3.0,  // 0%
    3.1,  // 10%
    3.2,  // 20%
    3.4,  // 30%
    3.5,  // 40%
    3.7,  // 50%
    3.9,  // 60%
    4.0,  // 70%
    4.05, // 80%
    4.1,  // 90%
    4.2   // 100%
};

#define DIVIDER_SCALE_FACTOR 1.53 // Resistor divider reduces measured voltage by this factor

const int LIPO_TABLE_SIZE = sizeof(lipo_voltage_table) / sizeof(lipo_voltage_table[0]);
const int SCALE_FACTOR = 100 / (LIPO_TABLE_SIZE - 1);

const int numReadings = 30; // Number of readings for the 30-second average
unsigned long previousMillis = 0;
const long interval = 1000; // Interval of 1 second (1000 ms)
int readings[numReadings];  // Array to store the last 30 readings
int readIndex = 0;          // Index of the current reading
long total = 0;             // Running total of the readings
bool first_reading = true;  // Readings after boot are zero
long average = 0;           // The calculated average

void power_setup()
{
    // Set up output for transistor to act as a current drain to stop battery protection circuit from turning off the power
    pinMode(CURRENT_DRAIN_PIN, OUTPUT);
    digitalWrite(CURRENT_DRAIN_PIN, 0);

    pinMode(PI_POWER_PIN, OUTPUT);
    digitalWrite(PI_POWER_PIN, 0);

    // Set resolution of ADC to match C6
    analogReadResolution(12);
    // Zero reading array
    for (int i = 0; i < numReadings; i++)
    {
        readings[i] = 0;
    }
    /*
    Set up microcontroller to occasionally wake up in case power is restored before the battery protection pack powers down
    */
    esp_sleep_enable_timer_wakeup(TIME_TO_SLEEP * uS_TO_S_FACTOR);
    D_println("Setup ESP32 to sleep for every " + String(TIME_TO_SLEEP) + " Seconds");

}

// Function to convert measured voltage into a percentage using linear interpolation
int get_lipo_percentage(float voltage)
{
    // Read boundary thresholds
    float min_v = pgm_read_float(&lipo_voltage_table[0]);
    float max_v = pgm_read_float(&lipo_voltage_table[LIPO_TABLE_SIZE - 1]);

    if (voltage <= min_v)
        return 0;
    if (voltage >= max_v)
        return 100;

    // Search the lookup table to find the bounding indices
    for (int i = 0; i < LIPO_TABLE_SIZE; i++)
    {
        float v_low = pgm_read_float(&lipo_voltage_table[i]);
        float v_high = pgm_read_float(&lipo_voltage_table[i + 1]);

        if (voltage >= v_low && voltage <= v_high)
        {
            // Linearly interpolate between the two array points for precise decimals
            float fraction = (voltage - v_low) / (v_high - v_low);
            return round((i + fraction) * SCALE_FACTOR);
        }
    }
    return 0;
}

void get_batt_percentage()
{
    unsigned long currentMillis = millis();

    // Check if 1 second has elapsed
    if (currentMillis - previousMillis >= interval)
    {
        previousMillis = currentMillis;
        // Subtract the oldest reading from the total
        total = total - readings[readIndex];
        // Read the new analog value (0 to 1023)
        readings[readIndex] = analogRead(BATT_VOLTAGE_PIN);

        // Add the new reading to the total
        total = total + readings[readIndex];

        if (first_reading && readIndex < numReadings)
        {
            average = total / (readIndex + 1);
        }
        else
        {
            // Calculate the average
            average = total / numReadings;
        }

        // Advance to the next position in the array (wrap around if at the end)
        readIndex = (readIndex + 1) % numReadings;

        if (first_reading && readIndex == 0)
            first_reading = false;

        current_batt_volts = 4.0 * DIVIDER_SCALE_FACTOR * average / 4095;
        current_batt_perc = get_lipo_percentage(current_batt_volts);
        // D_printf("Batt Voltage: %f, Perc: %d%%\n", current_batt_volts, current_batt_perc);
    }
}

void deep_sleep() 
{
    // Disconnect from the current network
    WiFi.disconnect(true);
    
    // Turn off the Wi-Fi radio completely
    WiFi.mode(WIFI_OFF);    
    
    D_println("Going to sleep now");
    D_flush();
    esp_deep_sleep_start();    
}

void power_control()
{
    get_batt_percentage();
    if (!video_power && current_batt_perc >= VIDEO_ON_THRESHOLD)
    {
        // Turn PI on, as battery voltage sufficient
        // Turn off power drain circuit as turning on PI
        digitalWrite(CURRENT_DRAIN_PIN, 0);
        digitalWrite(PI_POWER_PIN, 1);
        video_power = 1;
        pi_status = BOOTING;
        pi_shutdown_time = 0;
        // D_println("PI on, Drain off");
    }
    if (pi_status == UP && current_batt_perc <= VIDEO_OFF_THRESHOLD)
    {
        // Send shutdown command to PI but only if UP and responding
        shutdown_pi();
    }
    if (!video_power && !drain_power && current_batt_perc >= POWER_LOW_THRESHOLD)
    {
        // Turn on power drain circuit as PI is off
        digitalWrite(CURRENT_DRAIN_PIN, 1);
        drain_power = 1;
        // D_println("PI off, Drain on");
    }
    if (current_batt_perc <= POWER_LOW_THRESHOLD)
    {
        // Turn off power drain circuit.
        // This will cause the battery protection to turn off all power, as the current drawn will be below a threshold
        digitalWrite(CURRENT_DRAIN_PIN, 0);
        drain_power = 0;
        mic_power = 0;
        //Turn everything off
        deep_sleep();
        // D_println("Drain off");
    }
    if (pi_status == SHUTTING_DOWN && pi_shutdown_time > 0) {
        if (millis() - pi_shutdown_time > PI_SHUTDOWN_DELAY) {
            //PI should have cleanly powered down by now - power down PI
            digitalWrite(PI_POWER_PIN, 0);
            video_power = 0;
            mic_power = 1;
            pi_status = SHUTDOWN;
            D_println("PI off");
        }
    }

}

