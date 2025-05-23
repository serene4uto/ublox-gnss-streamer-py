import argparse
import sys
import logging
from threading import Event
import time

from ublox_gnss_streamer.ublox_gnss import UbloxGnss
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
    
    try:
        with UbloxGnss(
            args.port,
            int(args.baudrate),
            float(args.timeout),
            stop_event,
            idonly=True,
            enableubx=True,
            enablenmea=False,
            showhacc=True,
            verbose=True,
            measrate=30,
            navrate=1,
            navpriorate=30,
        ) as gna:
            gna.run()
            while not stop_event.is_set():
                time.sleep(1)
    except KeyboardInterrupt:
        stop_event.set()
            

if __name__ == "__main__":
    main()