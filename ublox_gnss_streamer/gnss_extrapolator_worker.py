from threading import Event
import threading
import time
import json
from ublox_gnss_streamer.gnss_extrapolator import GnssExtrapolator
from ublox_gnss_streamer.utils.logger import logger
from ublox_gnss_streamer.utils.threadsafe_deque import ThreadSafeDeque

class GnssExtrapolatorWorker:
    def __init__(
        self,
        gnss_extrapolator: GnssExtrapolator,
        stop_event: Event,
        gnss_raw_queue: ThreadSafeDeque,
        gnss_extra_queue: ThreadSafeDeque,
        extrapolate_interval: float = 0.0095  # Default extrapolation interval
    ):
        self.gnss_extrapolator = gnss_extrapolator
        self.stop_event = stop_event
        self.gnss_raw_queue = gnss_raw_queue
        self.gnss_extra_queue = gnss_extra_queue
        self.extrapolate_interval = extrapolate_interval
        self._thread = None

    def _worker_loop(self):
        while not self.stop_event.is_set():
            if self.stop_event.wait(self.extrapolate_interval):
                break

            if len(self.gnss_raw_queue) > 0:
                # New GNSS fix available: add it, but do NOT extrapolate
                gnss_data = self.gnss_raw_queue.popleft()
                logger.debug(f"Received GNSS data for extrapolation: {gnss_data}")
                
                # Validate lat/lon values before processing
                try:
                    lat_val = gnss_data.get("lat")
                    lon_val = gnss_data.get("lon")
                    
                    # Skip if lat/lon are empty strings, None, or not convertible to float
                    if lat_val is None or lon_val is None or lat_val == '' or lon_val == '':
                        logger.warning(f"Skipping GNSS extrapolation with invalid lat/lon: lat={lat_val}, lon={lon_val}")
                        continue
                    
                    # Try to convert to float to validate
                    lat_float = float(lat_val)
                    lon_float = float(lon_val)
                    
                    # Basic range validation for lat/lon
                    if not (-90 <= lat_float <= 90) or not (-180 <= lon_float <= 180):
                        logger.warning(f"Skipping GNSS extrapolation with out-of-range lat/lon: lat={lat_float}, lon={lon_float}")
                        continue
                        
                except (ValueError, TypeError) as e:
                    logger.warning(f"Skipping GNSS extrapolation with non-numeric lat/lon: lat={lat_val}, lon={lon_val}, error={e}")
                    continue
                
                # Create a copy with validated float values for the extrapolator
                validated_gnss_data = gnss_data.copy()
                validated_gnss_data["lat"] = lat_float
                validated_gnss_data["lon"] = lon_float
                
                self.gnss_extrapolator.add_fix(validated_gnss_data)
                self.gnss_extra_queue.append(
                    {
                        "timestamp": gnss_data["timestamp"],
                        "gnss_time": gnss_data["gnss_time"],
                        "lat": lat_float,
                        "lon": lon_float,
                        "quality": gnss_data["quality"],
                        "extrapolated": False,  # Mark as not extrapolated
                    }
                )
            else:
                # No new data: extrapolate to now and queue the result
                extrapolated = self.gnss_extrapolator.extrapolate(target_time=time.time())
                if extrapolated is not None:
                    logger.debug(f"Extrapolated GNSS data: {extrapolated}")
                    self.gnss_extra_queue.append(
                        {
                            "timestamp": extrapolated["timestamp"],
                            "gnss_time": None,
                            "lat": extrapolated["lat"],
                            "lon": extrapolated["lon"],
                            "quality": None,
                            "extrapolated": True,  # Mark as extrapolated
                        }
                    )
                    
    def run(self):
        self._thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._thread.start()
        logger.info("GNSS Extrapolator worker started.")
        return True

    def stop(self):
        self.stop_event.set()
        if self._thread:
            self._thread.join()
        logger.info("GNSS Extrapolator worker stopped.")
