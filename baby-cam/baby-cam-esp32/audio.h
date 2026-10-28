#include <driver/i2s_std.h>

#define SAMPLE_RATE 16000
#define BUFFER_SAMPLES 1024
#define AUDIO_QUEUE_BLOCKS 64

#define AUDIO_BUFFER_SAMPLES 32767
#define STREAM_BLOCK_SAMPLES 4096
#define MAX_AUDIO_CLIENTS 3

WiFiServer audioServer(8081);

int16_t audioBuffer[AUDIO_BUFFER_SAMPLES];

volatile uint32_t writeCount = 0;

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
            I2S_SLOT_MODE_MONO),

        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = (gpio_num_t)I2S_BCLK,
            .ws = (gpio_num_t)I2S_WS_LRCLK,
            .dout = I2S_GPIO_UNUSED,
            .din = (gpio_num_t)I2S_DOUT,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv = false}}};

    // SPH0645 with L/R low -> LEFT slot
    std_cfg.slot_cfg.slot_mask = I2S_STD_SLOT_LEFT;

    ESP_ERROR_CHECK(
        i2s_channel_init_std_mode(rx_handle, &std_cfg));

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
            audioBuffer[writeCount % AUDIO_BUFFER_SAMPLES] = 
                (int16_t)(i2sBuffer[i] >> 14);

            writeCount++;
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
    client.setNoDelay(true);
    
    D_println("Audio client connected");

    static int16_t txBuffer[STREAM_BLOCK_SAMPLES];

    while (client.connected())
    {
        if (!mic_power)
        {
            // Low power - close the stream
            break;
        }

        uint32_t currentWritePos = writeCount;

        uint32_t backlog = writeCount - readPos;

        // uint32_t distance =
        //     (currentWritePos +
        //      AUDIO_BUFFER_SAMPLES -
        //      readPos) %
        //     AUDIO_BUFFER_SAMPLES;

       if (backlog > AUDIO_BUFFER_SAMPLES)
       {
            D_printf("Client too slow (backlog %d) - resync\n", backlog);
            readPos = currentWritePos;
            continue;
        }

        size_t count = 0;

        while (readPos < currentWritePos &&
               count < STREAM_BLOCK_SAMPLES)
        {
            txBuffer[count++] =
                audioBuffer[readPos % AUDIO_BUFFER_SAMPLES];
            readPos++;
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
        // D_printf("Got %d bytes to send", bytesToSend);
        // D_flush();

        while (totalSent < bytesToSend &&
               client.connected())
        {
            uint32_t writeStart = millis();

            size_t sent =
                client.write(
                    data + totalSent,
                    bytesToSend - totalSent);
            uint32_t elapsed =
                millis() - writeStart;

            if (elapsed > 100)
            {
                D_printf(
                    "write blocked %lu ms\n",
                    elapsed);
            }
            if (sent > 0)
            {
                totalSent += sent;
            }
            else if (elapsed > 5000)
            {
                D_println("Write timeout");
                break;
            }
            vTaskDelay(1);        
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
            // Only start a new client if mic is powered on
            D_println("New audio listener");

            AudioClientContext *ctx =
                new AudioClientContext;

            ctx->client = client;

            //
            // Start new listeners "live"
            ctx->readPos = writeCount;

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

void setupAudioServer()
{
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
}