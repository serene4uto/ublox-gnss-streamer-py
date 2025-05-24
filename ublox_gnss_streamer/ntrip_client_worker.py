from threading import Thread, Event, Lock
from collections import deque

from .ntrip_client import NTRIPClient
from ublox_gnss_streamer.utils.logger import logger
from ublox_gnss_streamer.utils.threadsafe_deque import ThreadSafeDeque

class NTRIPClientWorker:
    def __init__(
        self, 
        host, 
        port, 
        mountpoint, 
        ntrip_version, 
        username, 
        password,
        reconnect_attempt_max=5,
        reconnect_attempt_wait_seconds=5,
        rtcm_timeout_seconds=5,
        nmea_max_length=82,
        nmea_min_length=0,
        ntrip_server_hz=1,
        stop_event: Event = None,
        nmea_queue: ThreadSafeDeque = None,
        rtcm_queue: ThreadSafeDeque = None,
    ):
        self._client = NTRIPClient(
            host=host,
            port=port,
            mountpoint=mountpoint,
            ntrip_version=ntrip_version,
            username=username,
            password=password,
            logdebug=logger.debug,
            loginfo=logger.info,
            logwarn=logger.warning,
            logerr=logger.error,
        )
        self._client.reconnect_attempt_max = reconnect_attempt_max
        self._client.reconnect_attempt_wait_seconds = reconnect_attempt_wait_seconds
        self._client.rtcm_timeout_seconds = rtcm_timeout_seconds
        self._client.nmea_parser.nmea_max_length = nmea_max_length
        self._client.nmea_parser.nmea_min_length = nmea_min_length
        
        self.rtcm_request_rate = 1.0 / ntrip_server_hz
        self.stop_event = stop_event
        self._thread = None
    
        self.nmea_queue = nmea_queue
        self.rtcm_queue = rtcm_queue
        
    def _worker_loop(self):

        while not self.stop_event.is_set():
            if self.stop_event.wait(self.rtcm_request_rate):
                break
            
            # get nmea and send
            if self.nmea_queue is not None:
                if len(self.nmea_queue) > 0:
                    nmea = self.nmea_queue.popleft()
                    logger.debug(f"Received NMEA: {nmea}")
                    self._client.send_nmea(nmea)
                else:
                    logger.debug("NMEA RX queue is empty")
                        
            # get rtcm from ntrip and send to rtcm_queue
            if self.rtcm_queue is not None:
                for rtcm in self._client.recv_rtcm():
                    if rtcm is not None:
                        self.rtcm_queue.append(rtcm)
                        logger.debug(f"Received RTCM: {rtcm}")
            
    def run(self):

        if not self._client.connect():
            logger.error('Unable to connect to NTRIP server')
            return False
        
        self._thread = Thread(target=self._worker_loop, daemon=True)
        self._thread.start()
        
        return True
        
    def stop(self):
        self.stop_event.set()
        if self._thread is not None:
            self._thread.join()
