import queue
import threading
import time
import subprocess
import requests

import numpy as np

from PyQt6.QtCore import QThread, pyqtSignal


class AudioStreamer(QThread):
    """
    Streams PCM audio from an ESP32 HTTP endpoint to HDMI via ALSA.

    The HTTP receiver and ALSA playback are deliberately decoupled.

    Brief queue starvation does NOT restart ALSA.  ALSA is restarted only
    when the HTTP source is known to have disconnected or ALSA itself dies.

    Also maintains a 0.0 .. 1.0 volume level based on RMS over the
    most recent 100 ms of audio.
    """

    volume_changed = pyqtSignal(float)
    status_changed = pyqtSignal(str)

    SOURCE_TIMEOUT = 1.5
    HTTP_READ_TIMEOUT = 2.0

    SAMPLE_RATE = 16000
    CHANNELS = 2

    # 1024 mono samples at 16 kHz = 64 ms
    BLOCK_SAMPLES = 1024

    # Fade length = 10 ms
    FADE_SAMPLES = 160

    # 4 blocks = approximately 256 ms prebuffer
    PREBUFFER_BLOCKS = 6

    # Maximum queued audio = approximately 512 ms
    MAX_QUEUE_BLOCKS = 32
    TARGET_QUEUE_BLOCKS = 6

    HTTP_CHUNK_SIZE = 2048

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

        self._last_audio_time = 0.0
        self._audio_time_lock = threading.Lock()
        self._stop_event = threading.Event()

        # Indicates that the ESP32 HTTP connection is currently alive.
        #
        # IMPORTANT:
        # Queue starvation while this is set is NOT considered a
        # disconnection.
        self._source_connected = threading.Event()

        self.audio_queue = queue.Queue(
            maxsize=self.MAX_QUEUE_BLOCKS
        )

        self.player = None

        # Protect access to self.player because the receiver/playback
        # threads and aplay monitor can all be active at different times.
        self._player_lock = threading.Lock()

        # Volume meter state
        self._level_samples = np.zeros(
            self.LEVEL_WINDOW_SAMPLES,
            dtype=np.float32,
        )

        self._level_position = 0

        self.current_volume_level = 0.0
        self.display_volume_level = 0.0

        self._volume_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start_stream(self):
        if self.isRunning():
            return

        self._stop_event.clear()
        self._source_connected.clear()
        with self._audio_time_lock:
            self._last_audio_time = 0.0
        
        self._clear_queue()

        self.start()

    def stop_stream(self):
        if not self.isRunning():
            return

        self._stop_event.set()
        self._source_connected.clear()

        self._clear_queue()
        self._stop_player()

        self.wait(3000)

    def is_streaming(self):
        return (
            self.isRunning()
            and not self._stop_event.is_set()
        )

    def volume_level(self):
        with self._volume_lock:
            return self.display_volume_level

    # ------------------------------------------------------------------
    # Main QThread
    # ------------------------------------------------------------------

    def run(self):

        self.status_changed.emit(
            "Starting audio stream"
        )

        receiver = threading.Thread(
            target=self._http_receiver,
            daemon=True,
        )

        receiver.start()

        try:
            self._playback()

        finally:

            self._stop_event.set()
            self._source_connected.clear()

            self._stop_player()

            receiver.join(timeout=1.0)

            self.status_changed.emit(
                "Audio stream stopped"
            )
            
    def _mark_audio_received(self):
        with self._audio_time_lock:
            self._last_audio_time = time.monotonic()


    def _source_is_alive(self):
        if not self._source_connected.is_set():
            return False

        with self._audio_time_lock:
            last_audio = self._last_audio_time

        return (
            time.monotonic() - last_audio
            < self.SOURCE_TIMEOUT
        )

    # ------------------------------------------------------------------
    # HTTP receiver
    # ------------------------------------------------------------------

    def _http_receiver(self):

        self.status_changed.emit(
            "Connecting to ESP32"
        )

        while not self._stop_event.is_set():

            # Always start a new HTTP connection with an empty byte buffer.
            #
            # This prevents a partial PCM block from a dead connection
            # being combined with data from the next connection.
            pending_pcm = bytearray()

            try:
                with requests.get(
                    self.esp32_url,
                    stream=True,
                    timeout=(5, self.HTTP_READ_TIMEOUT),
                ) as response:
                    response.raise_for_status()

                    self._source_connected.set()
                    self._mark_audio_received()

                    self.status_changed.emit(
                        "ESP32 audio connected"
                    )

                    mono_bytes_per_block = (
                        self.BLOCK_SAMPLES * 2
                    )

                    for chunk in response.iter_content(
                        chunk_size=self.HTTP_CHUNK_SIZE
                    ):

                        if self._stop_event.is_set():
                            break

                        if not chunk:
                            continue

                        self._mark_audio_received()
                        pending_pcm.extend(chunk)

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

                            stereo = self._process_audio(
                                mono
                            )

                            self._put_audio(
                                stereo
                            )

                    # If iter_content finishes without an exception,
                    # the HTTP connection has ended normally.
                    #
                    # Unless we're deliberately stopping, treat this
                    # exactly like a disconnect.
                    if not self._stop_event.is_set():

                        self._source_connected.clear()

                        self.status_changed.emit(
                            "ESP32 audio connection closed"
                        )

                        self._clear_queue()

            except Exception as e:

                if self._stop_event.is_set():
                    break

                self._source_connected.clear()

                # Discard anything left from the old connection.
                self._clear_queue()

                self.status_changed.emit(
                    f"Audio connection error: {e}"
                )

                # Give the ESP32/network a moment before reconnecting.
                time.sleep(1.0)

    # ------------------------------------------------------------------
    # Audio processing
    # ------------------------------------------------------------------

    def _process_audio(self, mono):

        # Convert to float before removing the large microphone DC offset.
        samples_float = mono.astype(np.float32)

        # Remove microphone DC offset.
        samples_float -= np.mean(samples_float)

        # Meter is based on the corrected signal.
        self._update_volume_level(
            samples_float
        )

        # Apply speaker gain.
        output = samples_float * self.gain

        output = np.clip(
            output,
            -32768,
            32767,
        ).astype(np.int16)

        # HDMI device requires stereo.
        stereo = np.empty(
            len(output) * 2,
            dtype=np.int16,
        )

        stereo[0::2] = output
        stereo[1::2] = output

        return stereo

    # ------------------------------------------------------------------
    # Volume meter
    # ------------------------------------------------------------------

    def _update_volume_level(self, samples):

        samples_float = samples / 32768.0

        offset = 0

        while offset < len(samples_float):

            count = min(
                len(samples_float) - offset,
                self.LEVEL_WINDOW_SAMPLES
                - self._level_position,
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

            if (
                self._level_position
                >= self.LEVEL_WINDOW_SAMPLES
            ):

                rms = np.sqrt(
                    np.mean(
                        self._level_samples ** 2
                    )
                )

                rms = max(rms, 1e-9)

                db = 20.0 * np.log10(rms)

                MIN_DB = -60.0
                MAX_DB = -20.0

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
                    if (
                        level
                        > self.display_volume_level
                    ):

                        self.display_volume_level += (
                            level
                            - self.display_volume_level
                        ) * 0.6

                    # Slow decay
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

                self._level_position = 0

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    def _put_audio(self, audio):

        try:

            self.audio_queue.put_nowait(
                audio
            )

        except queue.Full:

            # Drop the oldest block rather than allowing latency
            # to build up.
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                pass

            try:
                self.audio_queue.put_nowait(
                    audio
                )
            except queue.Full:
                pass

    #     qsize = self.audio_queue.qsize()

    #     if qsize <= 1:
    #         print(
    #             f"Audio queue LOW: {qsize} blocks "
    #             f"({qsize * self.BLOCK_SAMPLES / self.SAMPLE_RATE:.3f}s)"
    #         )        

    def _clear_queue(self):

        while True:

            try:
                self.audio_queue.get_nowait()

            except queue.Empty:
                break

    # ------------------------------------------------------------------
    # ALSA
    # ------------------------------------------------------------------

    def _start_player(self):

        player = subprocess.Popen(
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

                # 4096 frames = 256 ms at 16 kHz
                "--buffer-size=4096",

                # 1024 frames = 64 ms
                "--period-size=1024",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

        with self._player_lock:
            self.player = player

        self.status_changed.emit(
            f"ALSA started (pid {player.pid})"
        )

        threading.Thread(
            target=self._monitor_aplay,
            args=(player,),
            daemon=True,
        ).start()

    def _stop_player(self):

        with self._player_lock:

            player = self.player

            if player is None:
                return

            self.player = None

        try:

            print(
                "Stopping aplay:",
                player.pid,
                "returncode=",
                player.poll(),
            )

        except Exception:
            pass

        try:

            if player.stdin:

                player.stdin.close()

        except Exception:
            pass

        try:

            player.terminate()

            player.wait(
                timeout=1
            )

        except Exception:

            try:
                player.kill()
            except Exception:
                pass

    def _monitor_aplay(self, player):

        try:

            for line in player.stderr:

                text = line.decode(
                    errors="replace"
                ).strip()

                if text:

                    print(
                        "aplay:",
                        text
                    )

        except Exception as e:

            print(
                "aplay monitor error:",
                e
            )

    # ------------------------------------------------------------------
    # Fade helpers
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    def _playback(self):

        while not self._stop_event.is_set():

            # --------------------------------------------------------------
            # Wait for a genuinely live source and enough FRESH audio.
            # --------------------------------------------------------------

            self.status_changed.emit(
                "Buffering audio"
            )

            while not self._stop_event.is_set():

                # First requirement:
                # the HTTP source must actually be alive.
                if not self._source_is_alive():

                    if self._source_connected.is_set():
                        self._source_connected.clear()

                    # Throw away anything left from the previous
                    # connection. We only want fresh audio after reconnect.
                    self._clear_queue()

                    time.sleep(0.05)
                    continue

                # Second requirement:
                # enough audio must have arrived from this connection.
                if (
                    self.audio_queue.qsize()
                    < self.PREBUFFER_BLOCKS
                ):

                    time.sleep(0.02)
                    continue

                # Both conditions are now satisfied.
                break

            if self._stop_event.is_set():
                break

            # --------------------------------------------------------------
            # Re-check immediately before starting ALSA.
            #
            # This closes the race where the ESP32 disappears between
            # the previous test and Popen().
            # --------------------------------------------------------------

            if not self._source_is_alive():

                self._clear_queue()
                continue

            self._start_player()

            self.status_changed.emit(
                "Audio playing"
            )

            first_block = True

            try:

                while not self._stop_event.is_set():

                    # ------------------------------------------------------
                    # Check ALSA.
                    # ------------------------------------------------------

                    with self._player_lock:
                        player = self.player

                    if player is None:
                        break

                    return_code = player.poll()

                    if return_code is not None:

                        self.status_changed.emit(
                            f"ALSA exited - restarting "
                            f"(code {return_code})"
                        )

                        break

                    # ------------------------------------------------------
                    # Get audio.
                    # ------------------------------------------------------

                    try:

                        block = self.audio_queue.get(
                            timeout=0.02
                        )

                    except queue.Empty:

                        # --------------------------------------------------
                        # No audio arrived for 250 ms.
                        #
                        # This is NOT automatically a disconnect.
                        # Check whether the ESP32 is still sending data.
                        # --------------------------------------------------

                        if self._source_is_alive():
                            continue

                        # --------------------------------------------------
                        # Genuine source loss.
                        # --------------------------------------------------

                        self._source_connected.clear()

                        self._clear_queue()

                        self.status_changed.emit(
                            "Audio source disconnected"
                        )

                        break

                    # ------------------------------------------------------
                    # One last source check before writing.
                    # ------------------------------------------------------

                    if not self._source_is_alive():

                        self._source_connected.clear()

                        self._clear_queue()

                        self.status_changed.emit(
                            "Audio source disconnected"
                        )

                        break

                    # ------------------------------------------------------
                    # Fade in first block after reconnect.
                    # ------------------------------------------------------

                    if first_block:

                        block = self._fade_in(
                            block
                        )

                        first_block = False

                    # print(
                    #     f"QUEUE OUT {time.monotonic():.3f} "
                    #     f"size={self.audio_queue.qsize()}"
                    # )

                    self._write_audio(block)

            except BrokenPipeError:

                self.status_changed.emit(
                    "ALSA broken pipe - restarting"
                )

            except OSError as e:

                self.status_changed.emit(
                    f"ALSA error - restarting: {e}"
                )

            finally:

                self._stop_player()

            if self._stop_event.is_set():
                break

            # --------------------------------------------------------------
            # We are here because either:
            #
            # 1. ESP32 disappeared
            # 2. ALSA died
            #
            # If ESP32 disappeared, discard everything and wait for a
            # completely fresh connection.
            # --------------------------------------------------------------

            if not self._source_is_alive():

                self._source_connected.clear()

                self._clear_queue()

                self.status_changed.emit(
                    "Waiting for ESP32 audio reconnect"
                )

                # Don't immediately start ALSA again.
                time.sleep(0.1)

            else:

                # ALSA failed but ESP32 is still alive.
                # Give the system a moment before restarting.
                time.sleep(0.1)
    # ------------------------------------------------------------------
    # Write PCM to ALSA
    # ------------------------------------------------------------------

    def _write_audio(self, samples):

        with self._player_lock:

            player = self.player

        if (
            player is None
            or player.stdin is None
        ):
            raise OSError(
                "ALSA player is not running"
            )

        try:

            player.stdin.write(
                samples.tobytes()
            )

        except (
            BrokenPipeError,
            OSError,
        ):

            raise