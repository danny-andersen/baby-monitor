#!/usr/bin/env python3

import requests
import subprocess
import threading
import queue
import time
import numpy as np


# ============================================================
# Configuration
# ============================================================

ESP32_URL = "http://192.168.1.219/audio"

# HDMI 0
ALSA_DEVICE = "plughw:CARD=vc4hdmi0,DEV=0"

SAMPLE_RATE = 16000

# ESP32 microphone is mono
INPUT_CHANNELS = 1

# HDMI requires stereo
OUTPUT_CHANNELS = 2

# Microphone volume multiplier
GAIN = 2.0

# Audio block size.
#
# 1024 samples at 16 kHz = 64 ms
BLOCK_SAMPLES = 1024

# Fade length.
#
# 160 samples at 16 kHz = 10 ms
FADE_SAMPLES = 160

# Number of blocks required before playback starts.
#
# 16 × 64 ms = approximately 1 second
PREBUFFER_BLOCKS = 16

# Maximum buffered audio.
#
# 64 × 64 ms = approximately 4 seconds
MAX_QUEUE_BLOCKS = 64

# HTTP receive chunk size
HTTP_CHUNK_SIZE = 8192

# Reconnect delay
RECONNECT_DELAY = 1.0


# ============================================================
# Global state
# ============================================================

audio_queue = queue.Queue(
    maxsize=MAX_QUEUE_BLOCKS
)

stop_event = threading.Event()

network_connected = threading.Event()


# ============================================================
# Start aplay
# ============================================================

def start_player():

    command = [
        "aplay",

        "-D",
        ALSA_DEVICE,

        "-t",
        "raw",

        "-f",
        "S16_LE",

        "-c",
        str(OUTPUT_CHANNELS),

        "-r",
        str(SAMPLE_RATE),

        # ALSA buffer.
        #
        # The Python queue is the main buffer; this simply
        # gives ALSA some additional protection.
        "--buffer-size=65536",
        "--period-size=4096",
    ]

    print()
    print("Starting audio player:")
    print(" ".join(command))
    print()

    return subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        bufsize=0,
    )


# ============================================================
# Monitor aplay stderr
# ============================================================

def monitor_aplay(player):

    while not stop_event.is_set():

        try:
            line = player.stderr.readline()
        except Exception:
            break

        if not line:
            break

        message = line.decode(
            errors="replace"
        ).strip()

        if message:
            print("aplay:", message)


# ============================================================
# Apply gain to mono PCM
# ============================================================

def apply_gain(samples):

    if GAIN == 1.0:
        return samples

    samples_float = samples.astype(
        np.float32
    )

    samples_float *= GAIN

    np.clip(
        samples_float,
        -32768,
        32767,
        out=samples_float
    )

    return samples_float.astype(
        np.int16
    )


# ============================================================
# Convert mono → stereo
# ============================================================

def mono_to_stereo(samples):

    stereo = np.empty(
        len(samples) * 2,
        dtype=np.int16
    )

    stereo[0::2] = samples
    stereo[1::2] = samples

    return stereo


# ============================================================
# Fade the beginning of an audio block
# ============================================================

def fade_in(samples):

    frames = len(samples) // OUTPUT_CHANNELS

    fade = min(
        FADE_SAMPLES,
        frames
    )

    if fade <= 0:
        return samples

    ramp = np.linspace(
        0.0,
        1.0,
        fade,
        dtype=np.float32
    )

    count = fade * OUTPUT_CHANNELS

    # IMPORTANT:
    # Convert to float before multiplication.
    samples[:count] = (
        samples[:count].astype(np.float32)
        * np.repeat(ramp, OUTPUT_CHANNELS)
    ).astype(np.int16)

    return samples


# ============================================================
# Fade the end of an audio block
# ============================================================

def fade_out(samples):

    frames = len(samples) // OUTPUT_CHANNELS

    fade = min(
        FADE_SAMPLES,
        frames
    )

    if fade <= 0:
        return samples

    ramp = np.linspace(
        1.0,
        0.0,
        fade,
        dtype=np.float32
    )

    count = fade * OUTPUT_CHANNELS

    samples[-count:] = (
        samples[-count:].astype(np.float32)
        * np.repeat(ramp, OUTPUT_CHANNELS)
    ).astype(np.int16)

    return samples


# ============================================================
# Process incoming ESP32 PCM
# ============================================================

def process_audio(data):

    # HTTP chunks can contain an odd number of bytes.
    #
    # Keep the final byte until the next HTTP chunk.
    usable = len(data) & ~1

    if usable == 0:
        return b"", data

    pcm = np.frombuffer(
        data[:usable],
        dtype=np.int16
    )

    # Apply microphone gain
    pcm = apply_gain(pcm)

    # Convert mono → stereo
    stereo = mono_to_stereo(pcm)

    return (
        stereo.tobytes(),
        data[usable:]
    )


# ============================================================
# HTTP receiver thread
# ============================================================

def http_receiver():

    leftover = b""

    while not stop_event.is_set():

        try:

            print(
                "Connecting to ESP32:",
                ESP32_URL
            )

            with requests.get(
                ESP32_URL,
                stream=True,
                timeout=(5, 10),
            ) as response:

                response.raise_for_status()

                print("ESP32 audio connected")

                network_connected.set()

                for data in response.iter_content(
                    chunk_size=HTTP_CHUNK_SIZE
                ):

                    if stop_event.is_set():
                        break

                    if not data:
                        continue

                    # Add any incomplete sample from the
                    # previous HTTP packet.
                    data = leftover + data

                    stereo, leftover = process_audio(
                        data
                    )

                    if not stereo:
                        continue

                    block_bytes = (
                        BLOCK_SAMPLES
                        * OUTPUT_CHANNELS
                        * 2
                    )

                    offset = 0

                    while offset < len(stereo):

                        block = stereo[
                            offset:
                            offset + block_bytes
                        ]

                        offset += len(block)

                        # Don't enqueue a partial final block.
                        #
                        # It is better to keep the data for the
                        # next HTTP chunk than to create timing
                        # irregularities.
                        if len(block) < block_bytes:
                            break

                        while not stop_event.is_set():

                            try:

                                audio_queue.put(
                                    block,
                                    timeout=0.5
                                )

                                break

                            except queue.Full:

                                # Playback is temporarily slower
                                # than the network.
                                continue

                print(
                    "ESP32 HTTP connection ended"
                )

        except Exception as e:

            if not stop_event.is_set():
                print(
                    "HTTP audio error:",
                    e
                )

        finally:

            network_connected.clear()

        if not stop_event.is_set():

            print(
                f"Reconnecting in "
                f"{RECONNECT_DELAY:.1f} seconds..."
            )

            stop_event.wait(
                RECONNECT_DELAY
            )


# ============================================================
# Playback thread
# ============================================================

def playback():

    player = None
    stderr_thread = None

    # --------------------------------------------------------
    # Wait for enough audio to build up a buffer.
    # --------------------------------------------------------

    print()
    print(
        f"Waiting for approximately "
        f"{PREBUFFER_BLOCKS * BLOCK_SAMPLES / SAMPLE_RATE:.1f}"
        f" seconds of audio..."
    )

    while (
        not stop_event.is_set()
        and audio_queue.qsize() < PREBUFFER_BLOCKS
    ):

        time.sleep(0.02)

    if stop_event.is_set():
        return

    print(
        "Audio buffer ready:",
        audio_queue.qsize(),
        "blocks"
    )

    # --------------------------------------------------------
    # Start ALSA
    # --------------------------------------------------------

    player = start_player()

    stderr_thread = threading.Thread(
        target=monitor_aplay,
        args=(player,),
        daemon=True,
    )

    stderr_thread.start()

    # True while we are outputting silence.
    in_silence = False

    # Last real audio block.
    #
    # Used as the basis for the fade-out when the queue
    # becomes empty.
    last_audio_block = None

    # --------------------------------------------------------
    # Main playback loop
    # --------------------------------------------------------

    while not stop_event.is_set():

        # ----------------------------------------------------
        # Check whether aplay is still alive.
        # ----------------------------------------------------

        if player.poll() is not None:

            print(
                "aplay exited with code",
                player.returncode
            )

            try:
                player.stdin.close()
            except Exception:
                pass

            try:
                player.wait(timeout=1)
            except Exception:
                pass

            # Restart
            try:

                player = start_player()

                stderr_thread = threading.Thread(
                    target=monitor_aplay,
                    args=(player,),
                    daemon=True,
                )

                stderr_thread.start()

            except Exception as e:

                print(
                    "Unable to restart aplay:",
                    e
                )

                time.sleep(1)

                continue

        # ----------------------------------------------------
        # Try to obtain the next audio block.
        # ----------------------------------------------------

        try:

            block = audio_queue.get(
                timeout=0.02
            )

        except queue.Empty:

            # ------------------------------------------------
            # Buffer has run dry.
            #
            # Only transition into silence once.
            # ------------------------------------------------

            if not in_silence:

                print(
                    "Audio buffer empty - "
                    "fading to silence"
                )

                if last_audio_block is not None:

                    fade_block = (
                        last_audio_block.copy()
                    )

                    fade_out(
                        fade_block
                    )

                    try:

                        player.stdin.write(
                            fade_block.tobytes()
                        )

                        player.stdin.flush()

                    except (
                        BrokenPipeError,
                        OSError
                    ) as e:

                        print(
                            "Audio playback error:",
                            e
                        )

                # ------------------------------------------------
                # Now output zeros.
                #
                # We don't need to repeatedly write silence at
                # maximum speed. One block at a time keeps ALSA
                # supplied without flooding its input.
                # ------------------------------------------------

                silence = np.zeros(
                    BLOCK_SAMPLES
                    * OUTPUT_CHANNELS,
                    dtype=np.int16
                ).tobytes()

                try:

                    player.stdin.write(
                        silence
                    )

                    player.stdin.flush()

                except (
                    BrokenPipeError,
                    OSError
                ) as e:

                    print(
                        "Audio playback error:",
                        e
                    )

                in_silence = True

            else:

                # We are already in silence.
                #
                # Keep ALSA supplied with one block.
                silence = np.zeros(
                    BLOCK_SAMPLES
                    * OUTPUT_CHANNELS,
                    dtype=np.int16
                ).tobytes()

                try:

                    player.stdin.write(
                        silence
                    )

                    player.stdin.flush()

                except (
                    BrokenPipeError,
                    OSError
                ):

                    break

            continue

        # ----------------------------------------------------
        # We have received real audio.
        # ----------------------------------------------------

        samples = np.frombuffer(
            block,
            dtype=np.int16
        ).copy()

        # ----------------------------------------------------
        # Coming back from silence?
        #
        # Fade the beginning of the first real block in.
        # ----------------------------------------------------

        if in_silence:

            print(
                "Audio restored - "
                "fading in"
            )

            fade_in(samples)

            in_silence = False

        # ----------------------------------------------------
        # Save this block.
        #
        # A copy is important because the queue's underlying
        # bytes must not be modified.
        # ----------------------------------------------------

        last_audio_block = samples.copy()

        # ----------------------------------------------------
        # Send to ALSA.
        # ----------------------------------------------------

        try:

            player.stdin.write(
                samples.tobytes()
            )

            player.stdin.flush()

        except (
            BrokenPipeError,
            OSError
        ) as e:

            print(
                "Audio playback error:",
                e
            )

            try:
                player.kill()
            except Exception:
                pass

            try:
                player.wait(timeout=1)
            except Exception:
                pass

            player = None

            # Recreate aplay on next iteration
            while (
                player is None
                and not stop_event.is_set()
            ):

                try:

                    player = start_player()

                    stderr_thread = threading.Thread(
                        target=monitor_aplay,
                        args=(player,),
                        daemon=True,
                    )

                    stderr_thread.start()

                except Exception as restart_error:

                    print(
                        "Could not restart aplay:",
                        restart_error
                    )

                    time.sleep(1)

    # --------------------------------------------------------
    # Shutdown
    # --------------------------------------------------------

    if player is not None:

        try:
            player.stdin.close()
        except Exception:
            pass

        try:
            player.terminate()
            player.wait(timeout=2)
        except Exception:

            try:
                player.kill()
            except Exception:
                pass


# ============================================================
# Main
# ============================================================

def main():

    print()
    print("============================================")
    print(" ESP32 Network Microphone → HDMI")
    print("============================================")
    print()
    print("ESP32 URL :", ESP32_URL)
    print("ALSA      :", ALSA_DEVICE)
    print("Sample rate:", SAMPLE_RATE)
    print("Input     : Mono / S16_LE")
    print("Output    : Stereo / S16_LE")
    print("Gain      :", GAIN)
    print(
        "Block     :",
        f"{BLOCK_SAMPLES / SAMPLE_RATE * 1000:.1f} ms"
    )
    print(
        "Prebuffer :",
        f"{PREBUFFER_BLOCKS * BLOCK_SAMPLES / SAMPLE_RATE:.2f} sec"
    )
    print(
        "Max queue :",
        f"{MAX_QUEUE_BLOCKS * BLOCK_SAMPLES / SAMPLE_RATE:.2f} sec"
    )
    print(
        "Fade      :",
        f"{FADE_SAMPLES / SAMPLE_RATE * 1000:.1f} ms"
    )
    print()

    # --------------------------------------------------------
    # Start network receiver
    # --------------------------------------------------------

    receiver_thread = threading.Thread(
        target=http_receiver,
        name="ESP32-Audio-Receiver",
        daemon=True,
    )

    receiver_thread.start()

    # --------------------------------------------------------
    # Run playback in the main thread
    # --------------------------------------------------------

    try:

        playback()

    except KeyboardInterrupt:

        print()
        print("Stopping...")

    finally:

        stop_event.set()

        receiver_thread.join(
            timeout=2
        )

        print("Stopped.")


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    main()