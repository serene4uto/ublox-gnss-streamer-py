from threading import Event, Thread
from datetime import datetime
from zoneinfo import ZoneInfo

from ublox_gnss_streamer.ublox_gnss import UbloxGnss
from ublox_gnss_streamer.utils.logger import logger
from ublox_gnss_streamer.utils.threadsafe_deque import ThreadSafeDeque
from ublox_gnss_streamer.utils.schemas import GnssDataSchema

class UbloxGnssWorker:
    def __init__(
        self,
        gnss: UbloxGnss,
        stop_event: Event = None,
        nmea_queue: ThreadSafeDeque = None,
        rtcm_queue: ThreadSafeDeque = None,
        gnss_queue: ThreadSafeDeque = None,
        poll_interval: float = 1.0,
    ):
        self.ublox_gnss = gnss
        
        self.stop_event = stop_event
        self.nmea_queue = nmea_queue 
        self.rtcm_queue = rtcm_queue
        self.gnss_queue = gnss_queue

        self.poll_interval = poll_interval
        self._thread = None

    def _worker_loop(self):
        try:
            while not self.stop_event.is_set():
                raw, parsed = self.ublox_gnss.poll()
                if parsed and hasattr(parsed, "identity"):
                    if parsed.identity == "NAV-PVT":
                        logger.debug(f"Parsed NAV-PVT: {parsed}")
                        if hasattr(parsed, "lat") \
                            and hasattr(parsed, "lon") \
                            and hasattr(parsed, "hMSL") \
                            and hasattr(parsed, "carrSoln") \
                            and hasattr(parsed, "fixType") \
                            and hasattr(parsed, "gnssFixOk"):
                            gnss_json = GnssDataSchema(
                                timestamp=datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
                                lat=parsed.lat,
                                lon=parsed.lon,
                                h_msl=parsed.hMSL/ 1000.0,  # Convert to meters
                                fix_type=parsed.fixType,
                                carr_soln=parsed.carrSoln,
                                gnss_fix_ok=parsed.gnssFixOk
                            ).json()
                            logger.debug(f"GNSS JSON Data: {gnss_json}")
                            self.gnss_queue.append(gnss_json)
                            
                    if parsed.identity == "GNGGA":
                        logger.debug(f"Parsed GNGGA: {parsed}")
                        # If parsed is bytes, decode; otherwise, convert to string
                        if isinstance(raw, bytes):
                            self.nmea_queue.append(
                                raw.decode('utf-8', errors='replace'))

                # Send any pending RTCM messages
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
