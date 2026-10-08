import queue
import threading
import time
import subprocess

import numpy as np

from PyQt6.QtCore import QThread, pyqtSignal


class AudioStreamer(QThread):
    """
    Streams PCM audio from an ESP32 HTTP endpoint to HDMI via ALSA.

    Also maintains a 0.0 .. 1.0 volume level based on RMS over
    the most recent 100 ms of audio.
    """

    # Emitted periodically with the current volume level (0.0 .. 1.0)
    volume_changed = pyqtSignal(float)

    # Useful for displaying status in the GUI
    status_changed = pyqtSignal(str)

    SAMPLE_RATE = 16000
    CHANNELS = 2

    BLOCK_SAMPLES = 1024
    FADE_SAMPLES = 160             # 10 ms
    PREBUFFER_BLOCKS = 4           # ~256ms
    MAX_QUEUE_BLOCKS = 8           # ~512ms

    HTTP_CHUNK_SIZE = 8192

    LEVEL_WINDOW_MS = 100
    LEVEL_WINDOW_SAMPLES = (
        SAMPLE_RATE * LEVEL_WINDOW_MS // 1000
    )

    def __init__(
        self,
        esp32_url,
        alsa_device="plughw:CARD=vc4hdmi0,DEV=0",
        gain=2.0,
        parent=None,
    ):
        super().__init__(parent)

        self.esp32_url = esp32_url
        self.alsa_device = alsa_device
        self.gain = gain

        self._stop_event = threading.Event()

        self.audio_queue = queue.Queue(
            maxsize=self.MAX_QUEUE_BLOCKS
        )

        self.player = None

        # Volume measurement
        self._level_samples = np.zeros(
            self.LEVEL_WINDOW_SAMPLES,
            dtype=np.float32,
        )

        self._level_position = 0

        self.current_volume_level = 0.0
        self.display_volume_level = 0.0

        self._volume_lock = threading.Lock()

    # ---------------------------------------------------------
    # Public control
    # ---------------------------------------------------------

    def start_stream(self):
        """Start the audio stream."""
        if self.isRunning():
            return

        self._stop_event.clear()

        # Empty any old buffered audio
        self._clear_queue()

        self.start()

    def stop_stream(self):
        """Stop the audio stream."""
        if not self.isRunning():
            return

        self._stop_event.set()

        # Wake anything waiting on the queue
        self._clear_queue()

        # Stop aplay
        self._stop_player()

        # Wait for the QThread to finish
        self.wait(3000)

    def is_streaming(self):
        return self.isRunning() and not self._stop_event.is_set()

    def volume_level(self):
        """Return current smoothed volume level, 0.0 .. 1.0."""
        with self._volume_lock:
            return self.display_volume_level

    # ---------------------------------------------------------
    # QThread entry point
    # ---------------------------------------------------------

    def run(self):
        self.status_changed.emit("Starting audio stream")

        receiver = threading.Thread(
            target=self._http_receiver,
            daemon=True,
        )

        receiver.start()

        try:
            self._playback()

        finally:
            self._stop_event.set()

            self._stop_player()

            receiver.join(timeout=1.0)

            self.status_changed.emit("Audio stream stopped")

    # ---------------------------------------------------------
    # HTTP receiver
    # ---------------------------------------------------------

    def _http_receiver(self):
        import requests

        self.status_changed.emit("Connecting to ESP32")

        pending_pcm = bytearray()

        while not self._stop_event.is_set():

            try:
                with requests.get(
                    self.esp32_url,
                    stream=True,
                    timeout=(5, None),
                ) as response:

                    response.raise_for_status()

                    self.status_changed.emit(
                        "ESP32 audio connected"
                    )

                    for chunk in response.iter_content(
                        chunk_size=self.HTTP_CHUNK_SIZE
                    ):

                        if self._stop_event.is_set():
                            break

                        if not chunk:
                            continue

                        pending_pcm.extend(chunk)

                        # ESP32 sends mono S16_LE
                        mono_bytes_per_block = (
                            self.BLOCK_SAMPLES * 2
                        )

                        while (
                            len(pending_pcm)
                            >= mono_bytes_per_block
                        ):

                            block_bytes = pending_pcm[
                                :mono_bytes_per_block
                            ]

                            del pending_pcm[
                                :mono_bytes_per_block
                            ]

                            mono = np.frombuffer(
                                block_bytes,
                                dtype=np.int16,
                            ).copy()

                            stereo = self._process_audio(mono)

                            self._put_audio(stereo)

            except Exception as e:

                if self._stop_event.is_set():
                    break

                self.status_changed.emit(
                    f"Audio connection error: {e}"
                )

                time.sleep(1)

    # ---------------------------------------------------------
    # Audio processing
    # ---------------------------------------------------------

    def _process_audio(self, mono):
        """
        Apply gain, calculate volume level and convert mono -> stereo.
        """

        # Apply gain in float so we can measure the actual level
        samples_float = mono.astype(np.float32)

        # Remove DC offset
        samples_float -= np.mean(samples_float)

        # Measure actual microphone audio level
        self._update_volume_level(samples_float)

        # Apply speaker gain
        output = samples_float * self.gain
        # Clip for actual audio output
        output = np.clip(output, -32768, 32767).astype(np.int16)
        # Mono -> stereo
        stereo = np.empty(len(output) * 2, dtype=np.int16)

        stereo[0::2] = output
        stereo[1::2] = output

        return stereo

    # ---------------------------------------------------------
    # Volume measurement
    # ---------------------------------------------------------

    def _update_volume_level(self, samples):
        """
        Calculate RMS over the most recent 100 ms and convert
        it to a 0.0 .. 1.0 display level using dBFS.
        """

        samples_float = samples / 32768.0

        offset = 0

        while offset < len(samples_float):

            count = min(
                len(samples_float) - offset,
                self.LEVEL_WINDOW_SAMPLES - self._level_position,
            )

            self._level_samples[
                self._level_position:
                self._level_position + count
            ] = samples_float[
                offset:
                offset + count
            ]

            self._level_position += count
            offset += count

            if self._level_position >= self.LEVEL_WINDOW_SAMPLES:

                # RMS
                rms = np.sqrt(
                    np.mean(
                        self._level_samples ** 2
                    )
                )

                # Prevent log10(0)
                rms = max(rms, 1e-9)

                peak = np.max(
                    np.abs(self._level_samples)
                )

                # Convert to dBFS
                db = 20.0 * np.log10(rms)

                # Meter range
                MIN_DB = -60.0
                MAX_DB = -20.0

                # Convert dB -> 0..1
                level = (
                    db - MIN_DB
                ) / (
                    MAX_DB - MIN_DB
                )

                level = float(
                    np.clip(level, 0.0, 1.0)
                )

                with self._volume_lock:

                    self.current_volume_level = level

                    # Fast attack
                    if level > self.display_volume_level:

                        self.display_volume_level += (
                            level
                            - self.display_volume_level
                        ) * 0.6

                    # Slower decay
                    else:

                        self.display_volume_level += (
                            level
                            - self.display_volume_level
                        ) * 0.15

                    display_level = (
                        self.display_volume_level
                    )

                self.volume_changed.emit(
                    display_level
                )
                # print(
                #     f"Audio RMS={rms:.5f} "
                #     f"dBFS={db:.1f} "
                #     f"peak={peak:.5f} "
                #     f"meter={display_level:.2f}"
                # )

                self._level_position = 0
    # ---------------------------------------------------------
    # Queue
    # ---------------------------------------------------------

    def _put_audio(self, audio):

        try:
            self.audio_queue.put_nowait(audio)
        except queue.Full:
            # Drop the oldest block to keep latency low
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                pass

            try:
                self.audio_queue.put_nowait(audio)
            except queue.Full:
                pass

    def _clear_queue(self):

        while True:

            try:
                self.audio_queue.get_nowait()

            except queue.Empty:
                break

    # ---------------------------------------------------------
    # ALSA playback
    # ---------------------------------------------------------

    def _start_player(self):

        self.player = subprocess.Popen(
            [
                "aplay",

                "-D",
                self.alsa_device,

                "-t",
                "raw",

                "-f",
                "S16_LE",

                "-c",
                "2",

                "-r",
                str(self.SAMPLE_RATE),

                "--buffer-size=4096",

                "--period-size=1024",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

        # Monitor aplay errors without blocking
        threading.Thread(
            target=self._monitor_aplay,
            daemon=True,
        ).start()

    def _stop_player(self):

        if self.player is None:
            return

        try:

            if self.player.stdin:
                self.player.stdin.close()

        except Exception:
            pass

        try:
            self.player.terminate()
            self.player.wait(timeout=1)

        except Exception:

            try:
                self.player.kill()
            except Exception:
                pass

        self.player = None

    def _monitor_aplay(self):

        if not self.player:
            return

        try:

            for line in self.player.stderr:

                if self._stop_event.is_set():
                    break

                text = line.decode(
                    errors="replace"
                ).strip()

                if text:
                    print("aplay:", text)

        except Exception:
            pass

    # ---------------------------------------------------------
    # Fade helpers
    # ---------------------------------------------------------

    def _fade_in(self, samples):

        samples = samples.astype(
            np.float32
        )

        count = min(
            self.FADE_SAMPLES,
            len(samples),
        )

        ramp = np.linspace(
            0.0,
            1.0,
            count,
            dtype=np.float32,
        )

        samples[:count] *= ramp

        return np.clip(
            samples,
            -32768,
            32767,
        ).astype(np.int16)

    def _fade_out(self, samples):

        samples = samples.astype(
            np.float32
        )

        count = min(
            self.FADE_SAMPLES,
            len(samples),
        )

        ramp = np.linspace(
            1.0,
            0.0,
            count,
            dtype=np.float32,
        )

        samples[-count:] *= ramp

        return np.clip(
            samples,
            -32768,
            32767,
        ).astype(np.int16)

    # ---------------------------------------------------------
    # Playback
    # ---------------------------------------------------------

    def _playback(self):

        self._start_player()

        # Wait until we have enough audio buffered
        self.status_changed.emit(
            "Buffering audio"
        )

        while (
            self.audio_queue.qsize()
            < self.PREBUFFER_BLOCKS
            and not self._stop_event.is_set()
        ):
            time.sleep(0.02)

        if self._stop_event.is_set():
            return

        self.status_changed.emit(
            "Audio playing"
        )

        pending_block = None
        in_silence = False

        try:

            while not self._stop_event.is_set():

                # Get first pending block
                if pending_block is None:

                    try:
                        pending_block = (
                            self.audio_queue.get(
                                timeout=0.2
                            )
                        )

                    except queue.Empty:
                        continue

                # Look one block ahead.
                try:

                    next_block = (
                        self.audio_queue.get(
                            timeout=0.1
                        )
                    )

                    # We have another real audio block.
                    # Therefore pending_block is safe to output.
                    self._write_audio(
                        pending_block
                    )

                    pending_block = next_block

                    in_silence = False

                except queue.Empty:

                    # No next block arrived.
                    # Fade the pending block to zero.
                    faded = self._fade_out(
                        pending_block
                    )

                    self._write_audio(faded)

                    pending_block = None

                    # Enter silence
                    in_silence = True

                    silence = np.zeros(
                        self.BLOCK_SAMPLES
                        * self.CHANNELS,
                        dtype=np.int16,
                    )

                    while (
                        in_silence
                        and not self._stop_event.is_set()
                    ):

                        try:

                            new_block = (
                                self.audio_queue.get(
                                    timeout=0.1
                                )
                            )

                            # Fade back in
                            new_block = (
                                self._fade_in(
                                    new_block
                                )
                            )

                            self._write_audio(
                                new_block
                            )

                            pending_block = None
                            in_silence = False

                        except queue.Empty:

                            self._write_audio(
                                silence
                            )

        except (BrokenPipeError, OSError):

            self.status_changed.emit(
                "ALSA playback stopped"
            )

        finally:
            self._stop_player()

    def _write_audio(self, samples):

        if (
            self.player is None
            or self.player.stdin is None
        ):
            return

        try:

            self.player.stdin.write(
                samples.tobytes()
            )

        except (
            BrokenPipeError,
            OSError,
        ):

            raise