import argparse
import sys
import logging
from threading import Event, Lock
import time
from collections import deque
import yaml

from ublox_gnss_streamer.ublox_gnss import UbloxGnss
from ublox_gnss_streamer.ublox_gnss_worker import UbloxGnssWorker
from ublox_gnss_streamer.ntrip_client import NTRIPClient
from ublox_gnss_streamer.ntrip_client_worker import NTRIPClientWorker
from ublox_gnss_streamer.tcp_publisher import TcpPublisher
from ublox_gnss_streamer.tcp_publisher_worker import TcpPublisherWorker
from ublox_gnss_streamer.gnss_extrapolator import GnssExtrapolator
from ublox_gnss_streamer.gnss_extrapolator_worker import GnssExtrapolatorWorker

from ublox_gnss_streamer.utils.logger import logger, ColoredFormatter, ColoredLogger
from ublox_gnss_streamer.utils.threadsafe_deque import ThreadSafeDeque

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="ublox_gnss_streamer"
    )
    
    # YAML config file
    parser.add_argument(
        "-y", "--yaml-config", type=str,
        help="Path to YAML configuration file"
    )
    
    # Ublox GNSS parameters
    parser.add_argument(
        "-p", "--serial-port", type=str, default="/dev/ttyACM0",
        help="Serial port to connect to the GNSS device"
    )
    parser.add_argument(
        "-b", "--serial-baudrate", type=int, default=38400,
        help="Baudrate for the serial connection"
    )
    parser.add_argument(
        "-t", "--serial-timeout", type=float, default=1.0,
        help="Timeout in secs for the serial connection"
    )
    parser.add_argument(
        "-i", "--serial-interface", type=str, default="UART1",
        help="Serial interface used on the module (e.g., UART1, USB, etc.)"
    )

    # NTRIP client parameters
    parser.add_argument(
        "-s", "--ntrip-host", type=str, default="ntrip.hi-rtk.io",
        help="NTRIP server host"
    )
    parser.add_argument(
        "-n", "--ntrip-port", type=int, default=2101,
        help="NTRIP server port"
    )
    parser.add_argument(
        "-m", "--ntrip-mountpoint", type=str, default="SNS_AUTO",
        help="NTRIP mountpoint"
    )
    parser.add_argument(
        "-u", "--ntrip-username", type=str, default="sns",
        help="NTRIP username"
    )
    parser.add_argument(
        "-w", "--ntrip-password", type=str, default="1234",
        help="NTRIP password"
    )

    # TCP publisher parameters
    parser.add_argument(
        "-a", "--tcp-host", type=str, default="0.0.0.0",
        help="TCP host to publish data to"
    )
    parser.add_argument(
        "-q", "--tcp-port", type=int, default=5000,
        help="TCP port to publish data to"
    )

    # others
    parser.add_argument(
        "-l", "--logger-level", default="info",
        choices=["debug", "info", "warning", "fatal", "error"],
        help="Set the logger level"
    )

    return parser.parse_args(argv)

def main(argv=None):
    args = parse_args(argv)

    # Prepare a dictionary of final config values
    config_dict = {}

    # Load YAML config if provided
    if args.yaml_config:
        try:
            with open(args.yaml_config, 'r') as file:
                yaml_config = yaml.safe_load(file)
                if yaml_config:
                    config_dict.update(yaml_config)
        except Exception as e:
            logger.error(f"Failed to load YAML config: {e}")
            sys.exit(1)

    # Override YAML config with CLI arguments (if set)
    for key in vars(args):
        cli_value = getattr(args, key)
        if cli_value is not None:
            config_dict[key] = cli_value
            
    # Log the final configuration
    for key, value in config_dict.items():
        logger.debug(f"Config {key}: {value}")
    
    # Set up logging
    logger.setLevel(getattr(logging, config_dict.get('logger_level', 'info').upper()))
    if not logger.hasHandlers():
        # This block ensures that the logger has a handler after class change
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(getattr(logging, config_dict.get('logger_level', 'info').upper()))
        formatter = ColoredFormatter(ColoredLogger.FORMAT)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
    logger.info("Starting ublox_gnss_streamer")
    # log all options
    logger.debug(f"Options: {args}")
    
    stop_event = Event()
    rtcm_queue = ThreadSafeDeque(maxlen=100)
    nmea_queue = ThreadSafeDeque(maxlen=100)
    gnss_raw_queue = ThreadSafeDeque(maxlen=100)
    gnss_extra_queue = ThreadSafeDeque(maxlen=100)
    
    try:
        ublox_gnss_worker = UbloxGnssWorker(
            gnss=UbloxGnss(
                port=config_dict.get('serial_port', args.serial_port),
                baudrate=config_dict.get('serial_baudrate', args.serial_baudrate),
                timeout=config_dict.get('serial_timeout', args.serial_timeout),
                enableubx=True,
                enablenmea=True,
                measrate=100,
                navrate=1,
                navpriorate=30,
                port_type=config_dict.get('serial_interface', args.serial_interface),
            ),
            stop_event=stop_event,
            nmea_queue=nmea_queue,
            rtcm_queue=rtcm_queue,
            gnss_queue=gnss_raw_queue,
            poll_interval=0.01
        )
        

        ntrip_client_worker = NTRIPClientWorker(
            client= NTRIPClient(
                host=config_dict.get('ntrip_host', args.ntrip_host),
                port=config_dict.get('ntrip_port', args.ntrip_port),
                mountpoint=config_dict.get('ntrip_mountpoint', args.ntrip_mountpoint),
                ntrip_version='NTRIP/2.0',
                username=config_dict.get('ntrip_username', args.ntrip_username),
                password=config_dict.get('ntrip_password', args.ntrip_password),
                reconnect_attempt_max=5,
                reconnect_attempt_wait_seconds=5,
                rtcm_timeout_seconds=5,
                nmea_max_length=250,
                nmea_min_length=0,
            ),
            ntrip_server_hz=1,
            stop_event=stop_event,
            nmea_queue=nmea_queue,
            rtcm_queue=rtcm_queue,
        )
        
        tcp_publisher_worker = TcpPublisherWorker(
            publisher=TcpPublisher(
                host=config_dict.get('tcp_host', args.tcp_host),
                port=config_dict.get('tcp_port', args.tcp_port),
            ),
            stop_event=stop_event,
            gnss_queue=gnss_extra_queue,
            broadcast_interval=0.001  # 1000 Hz broadcast rate
        )
        
        gnss_extrapolator_worker = GnssExtrapolatorWorker(
            gnss_extrapolator=GnssExtrapolator(
                max_buffer=2,
            ),
            stop_event=stop_event,
            gnss_raw_queue=gnss_raw_queue,
            gnss_extra_queue=gnss_extra_queue,
            extrapolate_interval = 0.0095  # Default extrapolation interval (100 Hz)
        )
        
        while not ublox_gnss_worker.run():
            time.sleep(1)
        
        while not ntrip_client_worker.run():
            time.sleep(1)
            
        while not tcp_publisher_worker.run():
            time.sleep(1)
            
        while not gnss_extrapolator_worker.run():
            time.sleep(1)
            
        logger.info("All workers started successfully.")
        
        # main loop
        while not stop_event.is_set():
            time.sleep(1)
            
    except KeyboardInterrupt:
        stop_event.set()
            

if __name__ == "__main__":
    main()