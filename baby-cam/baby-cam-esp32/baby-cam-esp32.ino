#include <WiFi.h>
#include <WebServer.h>
#include <driver/i2s_std.h>

// -------------------------
// I2S pins
// -------------------------
#define I2S_BCLK  0
#define I2S_DOUT  1
#define I2S_WS_LRCLK    2


#define SAMPLE_RATE 16000
#define BUFFER_SAMPLES 1024
#define AUDIO_QUEUE_BLOCKS 64

#include "baby-cam-defs.h"
#include "wifi-defs.h"
#include "batt_volt_sense.h"

WebServer server(8080);
WiFiServer audioServer(8081);

#define AUDIO_BUFFER_SAMPLES 32768
#define STREAM_BLOCK_SAMPLES 512
#define MAX_AUDIO_CLIENTS 3

int16_t audioBuffer[AUDIO_BUFFER_SAMPLES];

volatile uint32_t writePos = 0;

TaskHandle_t captureTaskHandle = nullptr;
TaskHandle_t audioServerTaskHandle = nullptr;

i2s_chan_handle_t rx_handle;

struct PcmBlock
{
    int16_t samples[BUFFER_SAMPLES];
    uint16_t sampleCount;
};

volatile bool audioCaptureActive = false;
volatile bool audioCaptureTaskRunning = false;

struct AudioClientContext
{
    WiFiClient client;
    uint32_t readPos;
};

// -------------------------
// Initialise I2S
// -------------------------
void setupI2S()
{
    i2s_chan_config_t chan_cfg =
        I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);

    ESP_ERROR_CHECK(i2s_new_channel(&chan_cfg, NULL, &rx_handle));

    i2s_std_config_t std_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE),

        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
            I2S_DATA_BIT_WIDTH_32BIT,
            I2S_SLOT_MODE_MONO
        ),

        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = (gpio_num_t)I2S_BCLK,
            .ws   = (gpio_num_t)I2S_WS_LRCLK,
            .dout = I2S_GPIO_UNUSED,
            .din  = (gpio_num_t)I2S_DOUT,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv   = false
            }
        }
    };

    // SPH0645 with L/R low -> LEFT slot
    std_cfg.slot_cfg.slot_mask = I2S_STD_SLOT_LEFT;

    ESP_ERROR_CHECK(
        i2s_channel_init_std_mode(rx_handle, &std_cfg)
    );

    ESP_ERROR_CHECK(i2s_channel_enable(rx_handle));

    Serial.println("I2S microphone started");

}

// Capture task: I2S -> PCM -> BUFFER
void audioCaptureTask(void *parameter)
{
    int32_t i2sBuffer[BUFFER_SAMPLES];

    uint32_t readErrors = 0;

    while (true)
    {
        size_t bytesRead = 0;

        esp_err_t err = i2s_channel_read(
            rx_handle,
            i2sBuffer,
            sizeof(i2sBuffer),
            &bytesRead,
            pdMS_TO_TICKS(50));

        if (err != ESP_OK)
        {
            readErrors++;
            continue;
        }

        if (bytesRead == 0)
        {
            continue;
        }

        size_t samplesRead =
            bytesRead / sizeof(int32_t);

        if (samplesRead > BUFFER_SAMPLES)
        {
            samplesRead = BUFFER_SAMPLES;
        }

        for (size_t i = 0; i < samplesRead; i++)
        {
            audioBuffer[writePos] =
                (int16_t)(i2sBuffer[i] >> 14);

            writePos++;

            if (writePos >= AUDIO_BUFFER_SAMPLES)
            {
                writePos = 0;
            }
        }
    }
}

void audioClientTask(void *parameter)
{
    AudioClientContext *ctx =
        (AudioClientContext *)parameter;

    WiFiClient client = ctx->client;

    uint32_t readPos = ctx->readPos;

    delete ctx;

    client.println("HTTP/1.1 200 OK");
    client.println("Content-Type: audio/L16; rate=16000; channels=1");
    client.println("Cache-Control: no-cache");
    client.println("Connection: close");
    client.println();

    D_println("Audio client connected");

    int16_t txBuffer[STREAM_BLOCK_SAMPLES];

    while (client.connected())
    {
        if (!mic_power)
        {
            //Low power - close the stream
            break;
        }

        uint32_t currentWritePos = writePos;

        uint32_t distance =
            (currentWritePos +
             AUDIO_BUFFER_SAMPLES -
             readPos)
            % AUDIO_BUFFER_SAMPLES;

        if (distance > (AUDIO_BUFFER_SAMPLES - 1024))
        {
            D_println("Client too slow - resync");
            readPos = currentWritePos;
            continue;
        }

        size_t count = 0;

        while (readPos != currentWritePos &&
               count < STREAM_BLOCK_SAMPLES)
        {
            txBuffer[count++] =
                audioBuffer[readPos];
            readPos++;
            if (readPos >= AUDIO_BUFFER_SAMPLES)
            {
                readPos = 0;
            }
        }

        if (count == 0)
        {
            vTaskDelay(pdMS_TO_TICKS(2));
            continue;
        }

        uint8_t *data =
            (uint8_t *)txBuffer;
        size_t bytesToSend =
            count * sizeof(int16_t);
        size_t totalSent = 0;

        while (totalSent < bytesToSend &&
               client.connected())
        {
            size_t sent =
                client.write(
                    data + totalSent,
                    bytesToSend - totalSent);
            if (sent == 0)
            {
                vTaskDelay(1);
                continue;
            }
            totalSent += sent;
        }
    }
    client.stop();
    D_println("Audio client disconnected");
    vTaskDelete(nullptr);
}

void audioServerTask(void *parameter)
{
    audioServer.begin();

    D_println("Audio server started");

    while (true)
   {
        WiFiClient client = audioServer.available();
        if (client && mic_power)
        {
            //Only start a new client if mic is powered on
            D_println("New audio listener");

            AudioClientContext *ctx =
                new AudioClientContext;

            ctx->client = client;

            //
            // Start new listeners "live"            
            ctx->readPos = writePos;

            xTaskCreate(
                audioClientTask,
                "AudioClient",
                8192,
                ctx,
                2,
                nullptr);
        }

       vTaskDelay(pdMS_TO_TICKS(10));
    }
    audioServer.close();
}

// -------------------------
// Status page
// -------------------------
void handleRoot()
{
    String json;

    json += "{";
    json += "battery: ";
    json += batt_percentage;
    json += ",";
    json += "video: ";
    json += video_power;
    json += ",";
    json += "microphone: ";
    json += mic_power;
    // json += ","
    json += "}";

    // html += "<html><body>";
    // html += "<h1>ESP32-C6 Microphone</h1>";
    // html += "<p>SPH0645LM4H</p>";
    // html += "<p>Sample rate: 16000 Hz</p>";
    // html += "<p>Format: 16-bit mono PCM</p>";
    // html += "<p>Batt Percentage:";
    // html += batt_percentage;
    // html += "</p>";
    // html += "<p><a href=\"/audio\">Audio stream</a></p>";
    // html += "</body></html>";
    server.send(200, "text/json", json);
}


// -------------------------
// Setup
// -------------------------
void setup()
{
    D_SerialBegin(115200);
    delay(1000);

    //Set up output for transistor to act as a current drain to stop battery protection circuit from turning off the power
    pinMode(CURRENT_DRAIN_PIN, OUTPUT);
    digitalWrite(CURRENT_DRAIN_PIN, 0);

    pinMode(PI_POWER_PIN, OUTPUT);
    digitalWrite(PI_POWER_PIN, 0);

    analogReadResolution(12);

    D_println();
    D_println("ESP32-C6 I2S microphone");

    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    D_print("Connecting to WiFi");

    while (WiFi.status() != WL_CONNECTED)
    {
        delay(500);
        D_print(".");
    }

    D_println();
    D_print("IP address: ");
    D_println(WiFi.localIP());

    setupI2S();

    xTaskCreate(
        audioCaptureTask,
        "AudioCapture",
        8192,
        nullptr,
        3,
        &captureTaskHandle);

    xTaskCreate(
        audioServerTask,
        "AudioServer",
        8192,
        nullptr,
        2,
        &audioServerTaskHandle);

    server.on("/", HTTP_GET, handleRoot);

    server.begin();

    D_println("HTTP server started");
}


// -------------------------
// Main loop
// -------------------------
void loop()
{
    //Check on power situation
    power_control();
    if (mic_power) {
        server.handleClient();
    }
    vTaskDelay(pdMS_TO_TICKS(10));
    // D_printf("Batttery perc: %f\n", batt_percentage);
    // delay(1000);
}