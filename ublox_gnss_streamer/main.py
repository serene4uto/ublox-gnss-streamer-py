import argparse
import sys
import logging
from threading import Event, Lock
import time
from collections import deque

from ublox_gnss_streamer.ublox_gnss import UbloxGnss
from ublox_gnss_streamer.ublox_gnss_worker import UbloxGnssWorker
from ublox_gnss_streamer.ntrip_client import NTRIPClient
from ublox_gnss_streamer.ntrip_client_worker import NTRIPClientWorker
from ublox_gnss_streamer.utils.logger import logger, ColoredFormatter, ColoredLogger

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="ublox_gnss_streamer")
    parser.add_argument(
        "-p", "--port", type=str, default="/dev/ttyACM0", help="Serial port to connect to the GNSS device"
    )
    parser.add_argument(
        "-b", "--baudrate", type=int, default=115200, help="Baudrate for the serial connection"
    )
    parser.add_argument(
        "-t", "--timeout", required=False, help="Timeout in secs", default=3, type=float
    )
    
    parser.add_argument(
        "-ll", "--logger-level", default="info", choices=["debug", "info", "warning", "fatal", "error"], 
        help="Set the logger level"
    )
    
    return parser.parse_args(argv)

def main(argv=None):
    
    args = parse_args(argv)
    
    # Set up logging
    logger.setLevel(getattr(logging, args.logger_level.upper()))
    if not logger.hasHandlers():
        # This block ensures that the logger has a handler after class change
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(getattr(logging, args.logger_level.upper()))
        formatter = ColoredFormatter(ColoredLogger.FORMAT)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
    logger.info("Starting ublox_gnss_streamer")
    # log all options
    logger.debug(f"Options: {args}")
    
    stop_event = Event()
    rtcm_queue = deque(maxlen=10)
    rtcm_queue_lock = Lock()
    nmea_queue = deque(maxlen=10)
    nmea_queue_lock = Lock()
    
    try:
        ublox_gnss_worker = UbloxGnssWorker(
            gnss=UbloxGnss(
                port=args.port,
                baudrate=args.baudrate,
                timeout=args.timeout,
                enableubx=True,
                enablenmea=True,
                measrate=1000,
                navrate=1,
                navpriorate=1,
            ),
            stop_event=stop_event,
            nmea_queue=nmea_queue,
            nmea_queue_lock=nmea_queue_lock,
            rtcm_queue=rtcm_queue,
            rtcm_queue_lock=rtcm_queue_lock,
            poll_interval=0.01
        )
        

        ntrip_client_worker = NTRIPClientWorker(
            host="ntrip.hi-rtk.io",
            port=2101,
            mountpoint="SNS_AUTO",
            ntrip_version='NTRIP/2.0',
            username="sns",
            password="1234",
            reconnect_attempt_max=5,
            reconnect_attempt_wait_seconds=5,
            rtcm_timeout_seconds=5,
            nmea_max_length=250,
            nmea_min_length=0,
            ntrip_server_hz=1,
            stop_event=stop_event,
            nmea_queue=nmea_queue,
            nmea_queue_lock=nmea_queue_lock,
            rtcm_queue=rtcm_queue,
            rtcm_queue_lock=rtcm_queue_lock,
        )
        
        while not ublox_gnss_worker.run():
            time.sleep(1)
        
        while not ntrip_client_worker.run():
            time.sleep(1)
        
        # main loop
        while not stop_event.is_set():
            time.sleep(1)
            
    except KeyboardInterrupt:
        stop_event.set()
            

if __name__ == "__main__":
    main()