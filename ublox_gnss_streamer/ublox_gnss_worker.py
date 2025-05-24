from threading import Lock, Event, Thread
from collections import deque
from ublox_gnss_streamer.ublox_gnss import UbloxGnss
from ublox_gnss_streamer.utils.logger import logger

class UbloxGnssWorker:
    def __init__(
        self,
        gnss: UbloxGnss,
        stop_event: Event = None,
        nmea_queue: deque = None,
        nmea_queue_lock: Lock = None,
        rtcm_queue: deque = None,
        rtcm_queue_lock: Lock = None,
        poll_interval: float = 1.0,
    ):
        self.ublox_gnss = gnss

        # Robustly initialize queues and locks if not provided
        self.nmea_queue = nmea_queue if nmea_queue is not None else deque(maxlen=10)
        self.nmea_queue_lock = nmea_queue_lock if nmea_queue_lock is not None else Lock()
        self.rtcm_queue = rtcm_queue if rtcm_queue is not None else deque()
        self.rtcm_queue_lock = rtcm_queue_lock if rtcm_queue_lock is not None else Lock()
        self.stop_event = stop_event if stop_event is not None else Event()

        self.poll_interval = poll_interval
        self._thread = None

    def _worker_loop(self):
        try:
            while not self.stop_event.is_set():
                raw, parsed = self.ublox_gnss.poll()
                if parsed and hasattr(parsed, "identity"):
                    if parsed.identity == "NAV-PVT":
                        logger.debug(f"Parsed NAV-PVT: {parsed}")
                    if parsed.identity == "GNGGA":
                        logger.debug(f"Parsed GNGGA: {parsed}")
                        with self.nmea_queue_lock:
                            # If parsed is bytes, decode; otherwise, convert to string
                            if isinstance(raw, bytes):
                                self.nmea_queue.append(
                                    raw.decode('utf-8', errors='replace'))

                # Send any pending RTCM messages
                with self.rtcm_queue_lock:
                    while self.rtcm_queue:
                        rtcm = self.rtcm_queue.popleft()
                        self.ublox_gnss.send_rtcm(rtcm)
                        logger.debug(f"RTCM message sent: {rtcm}")

                # Wait for the next poll interval, but allow prompt shutdown
                if self.stop_event.wait(self.poll_interval):
                    break
        except Exception as e:
            logger.error(f"Worker loop error: {e}", exc_info=True)

    def run(self):
        self.ublox_gnss.connect()
        self.ublox_gnss.config()

        self._thread = Thread(target=self._worker_loop, daemon=True)
        self._thread.start()
        logger.info("Ublox GNSS worker started.")
        return True

    def stop(self):
        self.stop_event.set()
        if self._thread is not None:
            self._thread.join()
        self.ublox_gnss.disconnect()
        logger.info("Ublox GNSS worker stopped.")

    def is_running(self):
        return self._thread.is_alive() if self._thread else False
