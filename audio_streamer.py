
import math
import queue
import subprocess
import threading
import time

import numpy as np
import requests

from PyQt6.QtCore import QThread, pyqtSignal


class AudioStreamer(QThread):
    """
    Three-stage ESP32 PCM audio streamer.

    Stage 1: HTTP receiver -> raw PCM queue
    Stage 2: Audio processor -> processed stereo queue
    Stage 3: Playback loop -> aplay

    Input:
        16 kHz, signed 16-bit little-endian, mono PCM from /audio.

    Output:
        16 kHz, signed 16-bit little-endian, stereo PCM via aplay.
    """

    status_changed = pyqtSignal(str)
    volume_changed = pyqtSignal(float)
    error_occurred = pyqtSignal(str)

    # Audio format
    SAMPLE_RATE = 16000
    INPUT_CHANNELS = 1
    OUTPUT_CHANNELS = 2
    SAMPLE_WIDTH_BYTES = 2

    # 1024 mono samples = 2048 bytes = 64 ms
    BLOCK_SAMPLES = 1024
    RAW_BLOCK_BYTES = BLOCK_SAMPLES * SAMPLE_WIDTH_BYTES

    # Queue capacities
    RAW_QUEUE_BLOCKS = 32
    PLAYBACK_QUEUE_BLOCKS = 32
    PREBUFFER_BLOCKS = 6

    # HTTP and reconnect handling
    HTTP_CHUNK_SIZE = 2048
    HTTP_CONNECT_TIMEOUT = 5.0
    HTTP_READ_TIMEOUT = 2.0
    RECONNECT_DELAY = 1.0
    SOURCE_TIMEOUT = 1.5

    # Audio processing
    DEFAULT_GAIN = 2.0
    FADE_SAMPLES = 160
    LEVEL_WINDOW_MS = 100
    LEVEL_MIN_DBFS = -60.0
    LEVEL_MAX_DBFS = -20.0

    def __init__(
        self,
        audio_url,
        alsa_device="plughw:CARD=vc4hdmi0,DEV=0",
        gain=DEFAULT_GAIN,
        parent=None,
    ):
        super().__init__(parent)

        self.audio_url = audio_url
        self.alsa_device = alsa_device
        self.gain = float(gain)

        self._stop_event = threading.Event()
        self.source_connected = threading.Event()

        self._audio_time_lock = threading.Lock()
        self._last_audio_time = 0.0

        self._player_lock = threading.Lock()
        self.player = None

        self.raw_queue = queue.Queue(
            maxsize=self.RAW_QUEUE_BLOCKS
        )
        self.audio_queue = queue.Queue(
            maxsize=self.PLAYBACK_QUEUE_BLOCKS
        )

        # Changes whenever a new HTTP stream is established.
        # Queue entries carry the generation that produced them.
        self._generation_lock = threading.Lock()
        self._generation = 0

        # Volume meter state
        self._level_window_samples = (
            self.SAMPLE_RATE * self.LEVEL_WINDOW_MS // 1000
        )
        self._level_buffer = np.empty(
            0, dtype=np.float32
        )
        self._display_level = 0.0

        # Prevent overlapping reconnect fades.
        self._need_fade_in = True

    # ---------------------------------------------------------
    # Public interface
    # ---------------------------------------------------------

    def start_stream(self):
        if self.isRunning():
            return

        self._stop_event.clear()
        self.source_connected.clear()

        with self._audio_time_lock:
            self._last_audio_time = 0.0

        self._clear_queue(self.raw_queue)
        self._clear_queue(self.audio_queue)

        self._level_buffer = np.empty(0, dtype=np.float32)
        self._display_level = 0.0
        self._need_fade_in = True

        self.start()

    def stop_stream(self):
        if not self.isRunning():
            return

        self._stop_event.set()
        self.source_connected.clear()

        self._clear_queue(self.raw_queue)
        self._clear_queue(self.audio_queue)

        self._stop_player()

        # Allow the HTTP receiver to exit from its read timeout.
        self.wait(4000)

    def run(self):
        receiver = threading.Thread(
            target=self._http_receiver,
            name="AudioHTTPReceiver",
            daemon=True,
        )
        processor = threading.Thread(
            target=self._audio_processor,
            name="AudioProcessor",
            daemon=True,
        )

        receiver.start()
        processor.start()

        try:
            self._playback()
        finally:
            self._stop_event.set()
            self.source_connected.clear()

            self._clear_queue(self.raw_queue)
            self._clear_queue(self.audio_queue)
            self._stop_player()

            receiver.join(timeout=3.0)
            processor.join(timeout=3.0)

    # ---------------------------------------------------------
    # Queue helpers
    # ---------------------------------------------------------

    @staticmethod
    def _clear_queue(q):
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                break

    def _put_latest(self, q, item):
        """
        Never block a producer waiting for queue space.
        If full, discard the oldest item to limit latency.
        """
        try:
            q.put_nowait(item)
            return
        except queue.Full:
            pass

        try:
            q.get_nowait()
        except queue.Empty:
            pass

        try:
            q.put_nowait(item)
        except queue.Full:
            pass

    def _current_generation(self):
        with self._generation_lock:
            return self._generation

    def _new_generation(self):
        with self._generation_lock:
            self._generation += 1
            return self._generation

    # ---------------------------------------------------------
    # Source health
    # ---------------------------------------------------------

    def _mark_audio_received(self):
        with self._audio_time_lock:
            self._last_audio_time = time.monotonic()

    def _source_is_alive(self):
        if not self.source_connected.is_set():
            return False

        with self._audio_time_lock:
            last_audio = self._last_audio_time

        return (
            last_audio > 0
            and time.monotonic() - last_audio < self.SOURCE_TIMEOUT
        )

    # ---------------------------------------------------------
    # Stage 1: HTTP receiver
    # ---------------------------------------------------------

    def _http_receiver(self):
        """
        Receive bytes and assemble complete raw PCM blocks.

        No NumPy processing, volume calculations, gain or stereo
        conversion is performed in this thread.
        """
        session = requests.Session()

        try:
            while not self._stop_event.is_set():
                pending = bytearray()
                connected_generation = None

                try:
                    self.status_changed.emit(
                        "Connecting to ESP32 audio"
                    )

                    with session.get(
                        self.audio_url,
                        stream=True,
                        timeout=(
                            self.HTTP_CONNECT_TIMEOUT,
                            self.HTTP_READ_TIMEOUT,
                        ),
                    ) as response:
                        response.raise_for_status()

                        connected_generation = self._new_generation()

                        self._clear_queue(self.raw_queue)
                        self._clear_queue(self.audio_queue)

                        with self._audio_time_lock:
                            self._last_audio_time = time.monotonic()

                        self.source_connected.set()

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

                            # now = time.monotonic()

                            # if not hasattr(self, "_last_http_chunk_time"):
                            #     self._last_http_chunk_time = now
                            #     self._http_chunk_count = 0

                            # dt = now - self._last_http_chunk_time
                            # self._last_http_chunk_time = now
                            # self._http_chunk_count += 1

                            # if dt > 0.100:
                            #     print(
                            #         f"HTTP CHUNK DELAY: {dt * 1000:.1f} ms "
                            #         f"size={len(chunk)}"
                            #     )

                            self._mark_audio_received()

                            # print(
                            #     f"HTTP RX: {len(chunk)} bytes "
                            #     f"dt={dt * 1000:.1f} ms"
                            # )                            

                            pending.extend(chunk)

                            # Emit exact 64 ms blocks, preserving
                            # any incomplete block for the next read.
                            while len(pending) >= self.RAW_BLOCK_BYTES:
                                raw_block = bytes(
                                    pending[:self.RAW_BLOCK_BYTES]
                                )
                                del pending[:self.RAW_BLOCK_BYTES]

                                self._put_latest(
                                    self.raw_queue,
                                    (
                                        connected_generation,
                                        raw_block,
                                    ),
                                )

                        if not self._stop_event.is_set():
                            self.status_changed.emit(
                                "ESP32 audio connection closed"
                            )

                except requests.RequestException as exc:
                    if not self._stop_event.is_set():
                        self.error_occurred.emit(
                            f"Audio HTTP error: {exc}"
                        )

                except Exception as exc:
                    if not self._stop_event.is_set():
                        self.error_occurred.emit(
                            f"Audio receiver error: {exc}"
                        )

                finally:
                    # Invalidate queued blocks from the old stream.
                    self.source_connected.clear()
                    self._clear_queue(self.raw_queue)
                    self._clear_queue(self.audio_queue)

                if not self._stop_event.is_set():
                    self.status_changed.emit(
                        "Waiting for ESP32 audio reconnect"
                    )
                    self._stop_event.wait(self.RECONNECT_DELAY)

        finally:
            session.close()

    # ---------------------------------------------------------
    # Stage 2: PCM processing
    # ---------------------------------------------------------

    def _audio_processor(self):
        """
        Convert raw mono PCM blocks into processed stereo blocks.
        This thread can perform NumPy work without blocking HTTP.
        """
        while not self._stop_event.is_set():
            try:
                generation, raw_block = self.raw_queue.get(
                    timeout=0.1
                )
            except queue.Empty:
                # print("Audio processor queue empty; waiting for data")
                continue

            if self._stop_event.is_set():
                break

            # Discard data from a previous HTTP connection.
            if generation != self._current_generation():
                continue

            if not self._source_is_alive():
                continue

            try:
                mono = np.frombuffer(
                    raw_block, dtype="<i2"
                )

                if len(mono) != self.BLOCK_SAMPLES:
                    continue

                stereo = self._process_audio(mono)

                if generation != self._current_generation():
                    continue

                if not self._source_is_alive():
                    continue

                self._put_latest(
                    self.audio_queue,
                    (generation, stereo),
                )

            except Exception as exc:
                self.error_occurred.emit(
                    f"Audio processing error: {exc}"
                )

    def _process_audio(self, mono):
        """
        Remove microphone DC offset, update the volume meter,
        apply gain and convert mono samples to stereo.
        """
        samples = mono.astype(np.float32)

        # The SPH0645 stream can have a large DC offset.
        samples -= np.mean(samples)

        self._update_volume_level(samples)

        samples *= self.gain
        np.clip(samples, -32768, 32767, out=samples)

        output = samples.astype(np.int16)

        stereo = np.empty(
            len(output) * self.OUTPUT_CHANNELS,
            dtype=np.int16,
        )
        stereo[0::2] = output
        stereo[1::2] = output

        return stereo

    # ---------------------------------------------------------
    # Volume meter
    # ---------------------------------------------------------

    def _update_volume_level(self, samples):
        """
        Calculate RMS over a 100 ms window and emit a smoothed
        0.0-1.0 value for the UI volume bar.
        """
        self._level_buffer = np.concatenate(
            (self._level_buffer, samples)
        )

        while (
            len(self._level_buffer)
            >= self._level_window_samples
        ):
            window = self._level_buffer[
                :self._level_window_samples
            ]

            self._level_buffer = self._level_buffer[
                self._level_window_samples:
            ]

            rms = float(
                np.sqrt(np.mean(window * window))
            )

            if rms <= 0.0:
                dbfs = self.LEVEL_MIN_DBFS
            else:
                dbfs = 20.0 * math.log10(rms / 32768.0)

            level = (
                (dbfs - self.LEVEL_MIN_DBFS)
                / (self.LEVEL_MAX_DBFS - self.LEVEL_MIN_DBFS)
            )
            level = max(0.0, min(1.0, level))

            # Faster attack, slower decay.
            if level > self._display_level:
                alpha = 0.6
            else:
                alpha = 0.15

            self._display_level += alpha * (
                level - self._display_level
            )

            self.volume_changed.emit(
                float(self._display_level)
            )

    # ---------------------------------------------------------
    # Stage 3: ALSA playback
    # ---------------------------------------------------------

    def _playback(self):
        while not self._stop_event.is_set():
            self.status_changed.emit("Buffering audio")

            # Wait for a live source and enough processed blocks.
            while not self._stop_event.is_set():
                if not self._source_is_alive():
                    self._clear_queue(self.audio_queue)
                    self._stop_event.wait(0.02)
                    continue

                if (
                    self.audio_queue.qsize()
                    < self.PREBUFFER_BLOCKS
                ):
                    self._stop_event.wait(0.02)
                    continue

                break

            if self._stop_event.is_set():
                break

            if not self._source_is_alive():
                continue

            generation = self._current_generation()

            try:
                self._start_player()

                self.status_changed.emit("Audio playing")

                first_block = True

                while not self._stop_event.is_set():
                    with self._player_lock:
                        player = self.player

                    if player is None:
                        break

                    return_code = player.poll()

                    if return_code is not None:
                        self.status_changed.emit(
                            f"ALSA exited (code {return_code}); restarting"
                        )
                        break

                    if not self._source_is_alive():
                        self.status_changed.emit(
                            "Audio source disconnected"
                        )
                        break

                    try:
                        block_generation, block = (
                            self.audio_queue.get(timeout=0.05)
                        )
                    except queue.Empty:
                        # print("Audio playback queue empty; waiting for data")
                        # A temporary empty queue is not, by itself,
                        # proof that the ESP32 has disconnected.
                        continue

                    if block_generation != generation:
                        continue

                    if generation != self._current_generation():
                        break

                    if not self._source_is_alive():
                        break

                    if first_block or self._need_fade_in:
                        block = self._fade_in(block)
                        first_block = False
                        self._need_fade_in = False

                    self._write_audio(block)

            except BrokenPipeError:
                self.status_changed.emit(
                    "ALSA broken pipe; restarting"
                )

            except OSError as exc:
                self.status_changed.emit(
                    f"ALSA error; restarting: {exc}"
                )

            finally:
                self._need_fade_in = True
                self._stop_player()

            if self._stop_event.is_set():
                break

            # Wait for the receiver to reconnect if the source died.
            if not self._source_is_alive():
                self._clear_queue(self.audio_queue)
                self.status_changed.emit(
                    "Waiting for ESP32 audio reconnect"
                )

            self._stop_event.wait(0.1)

    def _start_player(self):
        command = [
            "aplay",
            "-D", self.alsa_device,
            "-t", "raw",
            "-f", "S16_LE",
            "-c", str(self.OUTPUT_CHANNELS),
            "-r", str(self.SAMPLE_RATE),
            "--buffer-size=4096",
            "--period-size=1024",
        ]

        player = subprocess.Popen(
            command,
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
            name="AplayMonitor",
            daemon=True,
        ).start()

    def _write_audio(self, samples):
        with self._player_lock:
            player = self.player

        if player is None or player.stdin is None:
            raise OSError("ALSA player is not running")

        player.stdin.write(samples.tobytes())

    def _stop_player(self):
        with self._player_lock:
            player = self.player
            self.player = None

        if player is None:
            return

        try:
            if player.stdin is not None:
                player.stdin.close()
        except (BrokenPipeError, OSError):
            pass

        if player.poll() is None:
            try:
                player.terminate()
                player.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                player.kill()
                try:
                    player.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass

    def _monitor_aplay(self, player):
        """
        Drain aplay stderr so its pipe cannot fill and block it.
        """
        if player.stderr is None:
            return

        try:
            for line in iter(player.stderr.readline, b""):
                if self._stop_event.is_set():
                    break

                message = line.decode(
                    "utf-8", errors="replace"
                ).strip()

                if message:
                    print(f"aplay: {message}")

        except (OSError, ValueError):
            pass

    # ---------------------------------------------------------
    # Fades to suppress clicks at stream transitions
    # ---------------------------------------------------------

    def _fade_in(self, stereo):
        result = stereo.copy()

        frames = min(
            self.FADE_SAMPLES,
            len(result) // self.OUTPUT_CHANNELS,
        )

        if frames <= 1:
            return result

        ramp = np.linspace(
            0.0, 1.0, frames, dtype=np.float32
        )

        result_view = result[:frames * self.OUTPUT_CHANNELS]
        result_view = result_view.reshape(
            frames, self.OUTPUT_CHANNELS
        )

        result_view[:] = (
            result_view.astype(np.float32) * ramp[:, None]
        ).astype(np.int16)

        return result
