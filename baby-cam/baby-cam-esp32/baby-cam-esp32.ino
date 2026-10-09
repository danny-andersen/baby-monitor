#include <WiFi.h>
#include <WebServer.h>
#include <driver/i2s_std.h>

#include "wifi-defs.h"

// -------------------------
// I2S pins
// -------------------------
#define I2S_BCLK  0
#define I2S_DOUT  1
#define I2S_WS_LRCLK    2

#define SAMPLE_RATE 16000
#define BUFFER_SAMPLES 512
#define AUDIO_QUEUE_BLOCKS 64

WebServer server(80);

i2s_chan_handle_t rx_handle;

struct PcmBlock
{
    int16_t samples[BUFFER_SAMPLES];
    uint16_t sampleCount;
};

volatile bool audioCaptureActive = false;
volatile bool audioCaptureTaskRunning = false;

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

// Capture task: I2S -> PCM -> queue
void audioCaptureTask(void *parameter)
{
    QueueHandle_t audioQueue = (QueueHandle_t)parameter;

    int32_t i2sBuffer[BUFFER_SAMPLES];
    PcmBlock block;

    uint32_t droppedBlocks = 0;
    uint32_t readErrors = 0;

    while (audioCaptureActive)
    {
        size_t bytesRead = 0;

        esp_err_t err = i2s_channel_read(
            rx_handle,
            i2sBuffer,
            sizeof(i2sBuffer),
            &bytesRead,
            pdMS_TO_TICKS(50)
        );

        if (err != ESP_OK)
        {
            readErrors++;
            continue;
        }

        if (bytesRead == 0)
            continue;

        size_t samplesRead = bytesRead / sizeof(int32_t);

        if (samplesRead > BUFFER_SAMPLES)
            samplesRead = BUFFER_SAMPLES;

        block.sampleCount = samplesRead;

        for (size_t i = 0; i < samplesRead; i++)
        {
            // SPH0645: convert 32-bit I2S samples to 16-bit PCM
            block.samples[i] =
                (int16_t)(i2sBuffer[i] >> 14);
        }

        // Normally enqueue immediately.
        if (xQueueSend(audioQueue, &block, 0) != pdPASS)
        {
            // Queue full: discard the oldest queued block.
            PcmBlock discarded;

            if (xQueueReceive(audioQueue, &discarded, 0) == pdPASS)
            {
                droppedBlocks++;
            }

            // Keep the newest audio where possible.
            if (xQueueSend(audioQueue, &block, 0) != pdPASS)
            {
                droppedBlocks++;
            }
        }
    }

    Serial.printf(
        "Capture stopped: dropped blocks=%lu, I2S errors=%lu\n",
        (unsigned long)droppedBlocks,
        (unsigned long)readErrors
    );

    audioCaptureTaskRunning = false;
    vTaskDelete(nullptr);
}

// -------------------------
// HTTP audio stream
// -------------------------
void handleAudio()
{
    WiFiClient client = server.client();

    QueueHandle_t audioQueue = xQueueCreate(
        AUDIO_QUEUE_BLOCKS,
        sizeof(PcmBlock)
    );

    if (audioQueue == nullptr)
    {
        Serial.println("Failed to allocate audio queue");
        client.stop();
        return;
    }

    // Send HTTP headers manually, as in the existing implementation.
    client.println("HTTP/1.1 200 OK");
    client.println("Content-Type: audio/L16; rate=16000; channels=1");
    client.println("Cache-Control: no-cache");
    client.println("Connection: close");
    client.println();

    Serial.println("Audio client connected");

    audioCaptureActive = true;
    audioCaptureTaskRunning = true;

    BaseType_t taskResult = xTaskCreate(
        audioCaptureTask,
        "AudioCapture",
        8192,
        (void *)audioQueue,
        3,
        nullptr
    );

    if (taskResult != pdPASS)
    {
        audioCaptureActive = false;
        audioCaptureTaskRunning = false;

        Serial.println("Failed to start audio capture task");

        vQueueDelete(audioQueue);
        client.stop();
        return;
    }

    PcmBlock block;

    while (client.connected())
    {
        // Wait for captured audio without busy-waiting.
        if (xQueueReceive(
                audioQueue,
                &block,
                pdMS_TO_TICKS(100)) != pdPASS)
        {
            continue;
        }

        size_t bytesToSend =
            block.sampleCount * sizeof(int16_t);

        const uint8_t *data =
            reinterpret_cast<const uint8_t *>(block.samples);

        // Handle partial writes without silently losing the
        // unsent remainder of the current block.
        size_t totalSent = 0;

        while (totalSent < bytesToSend && client.connected())
        {
            size_t sent = client.write(
                data + totalSent,
                bytesToSend - totalSent
            );

            if (sent == 0)
                break;

            totalSent += sent;
        }

        if (totalSent != bytesToSend)
        {
            Serial.printf(
                "Incomplete audio block: sent %u of %u bytes\n",
                (unsigned)totalSent,
                (unsigned)bytesToSend
            );
            break;
        }
    }

    // Stop capture and wait until it has stopped using the queue.
    audioCaptureActive = false;

    while (audioCaptureTaskRunning)
    {
        vTaskDelay(pdMS_TO_TICKS(10));
    }

    vQueueDelete(audioQueue);

    client.stop();

    Serial.println("Audio client disconnected");
}

// -------------------------
// Status page
// -------------------------
void handleRoot()
{
    String html;

    html += "<html><body>";
    html += "<h1>ESP32-C6 Microphone</h1>";
    html += "<p>SPH0645LM4H</p>";
    html += "<p>Sample rate: 16000 Hz</p>";
    html += "<p>Format: 16-bit mono PCM</p>";
    html += "<p><a href=\"/audio\">Audio stream</a></p>";
    html += "</body></html>";

    server.send(200, "text/html", html);
}


// -------------------------
// Setup
// -------------------------
void setup()
{
    Serial.begin(115200);
    delay(1000);

    Serial.println();
    Serial.println("ESP32-C6 I2S microphone");

    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    Serial.print("Connecting to WiFi");

    while (WiFi.status() != WL_CONNECTED)
    {
        delay(500);
        Serial.print(".");
    }

    Serial.println();
    Serial.print("IP address: ");
    Serial.println(WiFi.localIP());

    setupI2S();

    server.on("/", HTTP_GET, handleRoot);
    server.on("/audio", HTTP_GET, handleAudio);

    server.begin();

    Serial.println("HTTP server started");
}


// -------------------------
// Main loop
// -------------------------
void loop()
{
    server.handleClient();
}