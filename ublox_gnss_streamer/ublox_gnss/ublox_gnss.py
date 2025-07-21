
from queue import Empty, Queue
from collections import deque
from threading import Event, Thread
import time

from serial import Serial

from pynmeagps import (
    NMEAMessageError, 
    NMEAParseError
)
from pyrtcm import (
    RTCMMessage, 
    RTCMMessageError, 
    RTCMParseError,
)

from pyubx2 import (
    NMEA_PROTOCOL,
    RTCM3_PROTOCOL,
    UBX_PROTOCOL,
    UBXMessage,
    UBXMessageError,
    UBXParseError,
    UBXReader,
)

from ublox_gnss_streamer.utils.logger import logger

DISCONNECTED = 0
CONNECTED = 1

PORT_TYPE = [
    "USB", "UART1", "UART2"
]

class UbloxGnss:
    def __init__(
        self, 
        port: str, 
        baudrate: int, 
        timeout: float,
        **kwargs
    ):

        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.enableubx = kwargs.get("enableubx", False)
        self.enablenmea = kwargs.get("enablenmea", False)
        self.measrate = kwargs.get("measrate", 1000) # in ms
        self.navrate = kwargs.get("navrate", 1) # in hz (how many measurements per solution)
        self.navpriorate = kwargs.get("navpriorate", 1) 
        self.port_type = kwargs.get("port_type", "USB")  # Default to USB, can be changed to UART1 or UART2
        self.stream = None
        self.connected = DISCONNECTED
        
        if self.port_type not in PORT_TYPE:
            raise ValueError(f"Invalid port type: {self.port_type}. Must be one of {PORT_TYPE}.")
        
    def connect(self):
        self.stream = Serial(self.port, self.baudrate, timeout=self.timeout)
        self.ubr = UBXReader(self.stream, protfilter = NMEA_PROTOCOL | RTCM3_PROTOCOL | UBX_PROTOCOL)
        self.connected = CONNECTED
        logger.info("GNSS connected.")

    def disconnect(self):
        if self.stream:
            self.stream.close()
        self.connected = DISCONNECTED
        logger.info("GNSS disconnected.")
        
    def _send_data(self, data):
        if self.stream and self.connected == CONNECTED:
            self.stream.write(data)
            logger.debug("Sent config data directly.")
            return True
        else:
            logger.error("Device not connected.")
            return False
    
    def poll(self):
        if not self.stream:
            raise RuntimeError("Device not connected.")
        try:
            raw, parsed_data = self.ubr.read()
            return raw, parsed_data
        except (
            UBXMessageError,
            UBXParseError,
            NMEAMessageError,
            NMEAParseError,
            RTCMMessageError,
            RTCMParseError,
        ) as err:
            logger.error(f"Error parsing data: {err}")
            return None, None

    def send_rtcm(self, rtcm):
        if self._send_data(rtcm):
            logger.debug("RTCM data sent.")
        
    def config(self):
        layers = 1
        transaction = 0
        cfg_data = []
        for port_type in ("USB", "UART1", "UART2"):
            if port_type == self.port_type:
                cfg_data.append((f"CFG_{port_type}_ENABLED", True))
                cfg_data.append((f"CFG_{port_type}_ENABLED", True))
            else:
                cfg_data.append((f"CFG_{port_type}_ENABLED", False))
        
        msg = UBXMessage.config_set(layers, transaction, cfg_data)
        self._send_data(msg.serialize())
        
        self._enable_out_ubx(self.enableubx)
        self._enable_out_nmea(self.enablenmea)
        self._enable_in_rtcm(True)
        logger.debug("Sent config data to enable RTCM input and UBX/NMEA output.")
        
        layers = 1
        transaction = 0
        cfg_data = [] 
        # config Dynamic Model as automotive
        cfg_data.append(("CFG_NAVSPG_DYNMODEL", 4)) # 4 = automotive
        msg = UBXMessage.config_set(layers, transaction, cfg_data)
        self._send_data(msg.serialize())
        logger.debug("Sent config data to set dynamic model to automotive.")
        
        layers = 1
        transaction = 0
        cfg_data = [] 
        # cfg rate
        cfg_data.append(("CFG_RATE_MEAS", self.measrate))
        cfg_data.append(("CFG_RATE_NAV", self.navrate))
        cfg_data.append(("CFG_RATE_NAV_PRIO", self.navpriorate))
        msg = UBXMessage.config_set(layers, transaction, cfg_data)
        self._send_data(msg.serialize())
        logger.debug("Sent config data to set measurement rate, navigation rate and navigation priority rate.")
        
    def _enable_in_rtcm(self, enable: bool):
        """
        Enable RTCM input.
        :param bool enable: enable RTCM
        """
        layers = 1
        transaction = 0
        cfg_data = []
        for port_type in (self.port_type,):
            cfg_data.append((f"CFG_{port_type}INPROT_RTCM3X", enable))

        msg = UBXMessage.config_set(layers, transaction, cfg_data)
        self._send_data(msg.serialize())

    def _enable_out_nmea(self, enable: bool):
        """
        Enable NMEA output (only GGA).
        :param bool enable: enable NMEA
        """
        layers = 1
        transaction = 0
        cfg_data = []
        for port_type in (self.port_type,):
            cfg_data.append((f"CFG_{port_type}OUTPROT_NMEA", enable))
            cfg_data.append((f"CFG_MSGOUT_NMEA_ID_GGA_{port_type}", 1 if enable else 0))

            # suppress all common NMEA messages on the specified port
            cfg_data.append((f"CFG_MSGOUT_NMEA_ID_GLL_{port_type}", 0))
            cfg_data.append((f"CFG_MSGOUT_NMEA_ID_GSA_{port_type}", 0))
            cfg_data.append((f"CFG_MSGOUT_NMEA_ID_GSV_{port_type}", 0))
            cfg_data.append((f"CFG_MSGOUT_NMEA_ID_RMC_{port_type}", 0))
            cfg_data.append((f"CFG_MSGOUT_NMEA_ID_VTG_{port_type}", 0))
            cfg_data.append((f"CFG_MSGOUT_NMEA_ID_ZDA_{port_type}", 0))
            cfg_data.append((f"CFG_MSGOUT_NMEA_ID_GST_{port_type}", 0))
            cfg_data.append((f"CFG_MSGOUT_NMEA_ID_GNS_{port_type}", 0))

        msg = UBXMessage.config_set(layers, transaction, cfg_data)
        self._send_data(msg.serialize())

    def _enable_out_ubx(self, enable: bool):
        """
        Enable UBX output (only NAV-PVT).
        :param bool enable: enable UBX
        """

        layers = 1
        transaction = 0
        cfg_data = []
        for port_type in (self.port_type,):
            cfg_data.append((f"CFG_{port_type}OUTPROT_UBX", enable))
            cfg_data.append((f"CFG_MSGOUT_UBX_NAV_PVT_{port_type}", 1 if enable else 0))
            # cfg_data.append((f"CFG_MSGOUT_UBX_NAV_COV_{port_type}", enable))

        msg = UBXMessage.config_set(layers, transaction, cfg_data)
        self._send_data(msg.serialize())
    
        
        
    
    
        