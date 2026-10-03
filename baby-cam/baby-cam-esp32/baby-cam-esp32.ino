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
#define BUFFER_SAMPLES 256

WebServer server(80);

i2s_chan_handle_t rx_handle;

int32_t i2sBuffer[BUFFER_SAMPLES];
int16_t pcmBuffer[BUFFER_SAMPLES];


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


// -------------------------
// HTTP audio stream
// -------------------------
void handleAudio()
{
    WiFiClient client = server.client();

    // Send HTTP headers manually
    client.println("HTTP/1.1 200 OK");
    client.println("Content-Type: audio/L16; rate=16000; channels=1");
    client.println("Cache-Control: no-cache");
    client.println("Connection: close");
    client.println();

    Serial.println("Audio client connected");

    while (client.connected())
    {
        size_t bytesRead = 0;

        esp_err_t err = i2s_channel_read(
            rx_handle,
            i2sBuffer,
            sizeof(i2sBuffer),
            &bytesRead,
            1000
        );

        if (err != ESP_OK)
        {
            Serial.printf("I2S read error: %d\n", err);
            continue;
        }

        if (bytesRead == 0)
            continue;

        size_t samples = bytesRead / sizeof(int32_t);

        for (size_t i = 0; i < samples; i++)
        {
            // SPH0645 -> 16-bit PCM
            pcmBuffer[i] = (int16_t)(i2sBuffer[i] >> 14);
        }

        size_t bytesToSend = samples * sizeof(int16_t);

        size_t sent = client.write(
            (uint8_t*)pcmBuffer,
            bytesToSend
        );

        if (sent != bytesToSend)
        {
            Serial.printf(
                "Short write: %d / %d\n",
                sent,
                bytesToSend
            );
            break;
        }

        yield();
    }

    Serial.println("Audio client disconnected");
    client.stop();
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