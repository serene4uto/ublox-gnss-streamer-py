from .ntrip_client import NTRIPClient
from threading import Thread, Event, Lock
from ublox_gnss_streamer.utils.logger import logger
from collections import deque

class NTRIPClientWorker:
    def __init__(
        self, 
        stop_event: Event,
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
        nmea_rxqueue: deque = None,
        nmea_rxqueue_lock : Lock = None,
        rtcm_txqueue: deque = None,
        rtcm_txqueue_lock : Lock = None,
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
    
        self.nmea_rxqueue : deque = nmea_rxqueue
        self.nmea_rxqueue_lock : Lock = nmea_rxqueue_lock
        self.rtcm_txqueue : deque = rtcm_txqueue
        self.rtcm_txqueue_lock : Lock = rtcm_txqueue_lock
        
    def _worker(self):

        while not self.stop_event.is_set():
            if self.stop_event.wait(self.rtcm_request_rate):
                break
            
            # get nmea and send
            if self.nmea_rxqueue is not None and self.nmea_rxqueue_lock is not None:
                with self.nmea_rxqueue_lock:
                    if len(self.nmea_rxqueue) > 0:
                        nmea = self.nmea_rxqueue.popleft()
                        logger.debug(f"Received NMEA: {nmea}")
                        self._client.send_nmea(nmea)
                    else:
                        logger.debug("NMEA RX queue is empty")
                        
            # get rtcm from ntrip and send to rtcm_txqueue
            if self.rtcm_txqueue is not None and self.rtcm_txqueue_lock is not None:
                with self.rtcm_txqueue_lock:
                    if len(self.rtcm_txqueue) > 0:
                        for raw_rtcm in self._client.recv_rtcm():
                            logger.debug(f"Received RTCM: {raw_rtcm}")
                            self.rtcm_txqueue.append(raw_rtcm)
                    else:
                        logger.debug("RTCM TX queue is empty")
            
    def run(self):

        if not self._client.connect():
            logger.error('Unable to connect to NTRIP server')
            return False
        
        self._thread = Thread(target=self._worker, daemon=True)
        self._thread.start()
        
        return True
        
    def stop(self):
        self.stop_event.set()
        if self._thread is not None:
            self._thread.join()
