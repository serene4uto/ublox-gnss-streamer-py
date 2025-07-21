from threading import Thread, Event, Lock
from collections import deque
import time

from .ntrip_client import NTRIPClient
from ublox_gnss_streamer.utils.logger import logger
from ublox_gnss_streamer.utils.threadsafe_deque import ThreadSafeDeque

class NTRIPClientWorker:
    def __init__(
        self, 
        client: NTRIPClient,
        ntrip_server_hz=1,
        stop_event: Event = None,
        nmea_queue: ThreadSafeDeque = None,
        rtcm_queue: ThreadSafeDeque = None,
        **kwargs
    ):
        self._client = client
        self.rtcm_request_rate = 1.0 / ntrip_server_hz
        self.stop_event = stop_event
        self._thread = None
    
        self.nmea_queue = nmea_queue
        self.rtcm_queue = rtcm_queue
        
        self._serial_port = kwargs.get('serial_port', None)
        self._serial_baudrate = kwargs.get('serial_baudrate', 9600)
        self._serial_timeout = kwargs.get('serial_timeout', 1.0)
        self._serial_stream = None
        
    def _worker_loop(self):
        
        if self._serial_port:
            import serial
            try:
                self._serial_stream = serial.Serial(
                    port=self._serial_port,
                    baudrate=self._serial_baudrate,
                    timeout=self._serial_timeout
                )
                logger.info(f"Connected to serial port {self._serial_port} at {self._serial_baudrate} baud.")
            except serial.SerialException as e:
                logger.error(f"Failed to open serial port {self._serial_port}: {e}")
                return
        
        rtcm_count = 0
        last_rate_time = time.time()

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
                        # logger.debug(f"Received RTCM: {rtcm}")
                        if self._serial_stream:
                            try:
                                self._serial_stream.write(rtcm)
                                logger.debug(f"Sent RTCM to serial: {rtcm}")
                            except serial.SerialException as e:
                                logger.error(f"Failed to write to serial port: {e}")
                        else:
                            self.rtcm_queue.append(rtcm)
                            logger.debug(f"Appended RTCM to queue: {rtcm}")
                        
            rtcm_count += 1
            
            if rtcm_count % 10 == 0:  # Report every 10 requests
                current_time = time.time()
                elapsed_time = current_time - last_rate_time
                if elapsed_time > 0:
                    rate = rtcm_count / elapsed_time
                    logger.info(f"RTCM request rate: {rate:.2f} Hz")
                    last_rate_time = current_time
                    rtcm_count = 0
                
            
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
