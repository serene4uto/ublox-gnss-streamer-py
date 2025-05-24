
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

class UbloxGnss:
    def __init__(
        self, port: str, 
        baudrate: int, 
        timeout: float, 
        stopevent: Event, 
        **kwargs
    ):

        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.stopevent = stopevent
         
        self.idonly = kwargs.get("idonly", True)
        self.enableubx = kwargs.get("enableubx", False)
        self.enablenmea = kwargs.get("enablenmea", False)
        self.showhacc = kwargs.get("showhacc", False)
        self.measrate = kwargs.get("measrate", 1000) # in ms
        self.navrate = kwargs.get("navrate", 1) # in hz (how many measurements per solution)
        self.navpriorate = kwargs.get("navpriorate", 1) 
        self.stream = None
        self.connected = DISCONNECTED
        self.lat = 0
        self.lon = 0
        self.alt = 0
        self.sep = 0

        self.verbose = kwargs.get("verbose", False)
        
        self.sendqueue = Queue(50)
        self.receivequeue = None
        self.nmea_gga_queue = deque(maxlen=10)
        self.nav_pvt_queue = deque(maxlen=10)
        self.nav_cov_queue = deque(maxlen=10)

    def __enter__(self):
        """
        Context manager enter routine.
        """

        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        """
        Context manager exit routine.

        Terminates app in an orderly fashion.
        """

        self.stop()
        
    def run(self):
        """
        Run GNSS reader/writer.
        """

        self.config()

        self.stream = Serial(self.port, self.baudrate, timeout=self.timeout)
        self.connected = CONNECTED
        self.stopevent.clear()

        read_thread = Thread(
            target=self._read_loop,
            args=(
                self.stream,
                self.stopevent,
                self.sendqueue,
                self.receivequeue,
                self.verbose
            ),
            daemon=True,
        )
        read_thread.start()


    def stop(self):
        """
        Stop GNSS reader/writer.
        """

        self.stopevent.set()
        self.connected = DISCONNECTED
        if self.stream is not None:
            self.stream.close()
            
            
    def _read_loop(self, 
                   stream: Serial, 
                   stopevent: Event, 
                   sendqueue: Queue, 
                   receivequeue: Queue, 
                   verbose: bool):
        """
        THREADED
        Reads and parses incoming GNSS data from the receiver,
        and sends any queued output data to the receiver.

        :param Serial stream: serial stream
        :param Event stopevent: stop event
        :param Queue sendqueue: queue for messages to send to receiver

        :param Queue receivequeue: queue for messages to receive from receiver
        :verbose bool: verbose mode
        """

        ubr = UBXReader(
            stream, protfilter=(NMEA_PROTOCOL | UBX_PROTOCOL | RTCM3_PROTOCOL)
        )
        while not stopevent.is_set():
            try:
                if stream.in_waiting:
                    raw, parsed_data = ubr.read()
                    if parsed_data and hasattr(parsed_data, "identity"):
                        
                        if parsed_data.identity == "NAV-PVT":
                            self.nav_pvt_queue.append((parsed_data))
                            
                        if parsed_data.identity == "NAV-COV":
                            self.nav_cov_queue.append((parsed_data))
                            
                        if parsed_data.identity == "GNGGA":
                            self.nmea_gga_queue.append((raw))
                            
                        # if receivequeue is not None:
                        #     receivequeue.put((raw, parsed_data))

                        if verbose == True:
                            # extract current navigation solution
                            # self._extract_coordinates(parsed_data)
    
                            # if it's an RXM-RTCM message, show which RTCM3 message
                            # it's acknowledging and whether it's been used or not.""
                            if parsed_data.identity == "RXM-RTCM":
                                nty = (
                                    f" - {parsed_data.msgType} "
                                    f"{'Used' if parsed_data.msgUsed > 0 else 'Not used'}"
                                )
                            else:
                                nty = ""
    
                            if self.idonly:
                                logger.debug((f"GNSS>> {parsed_data.identity}{nty}"))
                            else:
                                logger.debug((f"GNSS>> {parsed_data}{nty}"))


                # send any queued output data to receiver
                self._send_data(ubr.datastream, sendqueue, verbose)

            except (
                UBXMessageError,
                UBXParseError,
                NMEAMessageError,
                NMEAParseError,
                RTCMMessageError,
                RTCMParseError,
            ) as err:
                if verbose:
                    logger.error(f"Error parsing data: {err}")
                continue
            

    def _send_data(self, stream: Serial, sendqueue: Queue, verbose: bool):
        """
        Send any queued output data to receiver.
        Queue data is tuple of (raw_data, parsed_data).

        :param Serial stream: serial stream
        :param Queue sendqueue: queue for messages to send to receiver
        """

        if sendqueue is not None:
            try:
                while not sendqueue.empty():
                    data = sendqueue.get(False)
                    raw, parsed = data
                    if verbose == True:
                        source = "NTRIP>>" if isinstance(parsed, RTCMMessage) else "GNSS<<"
                        if self.idonly:
                            logger.debug(f"{source} {parsed.identity}")
                        else:
                            logger.debug(f"{source} {parsed}")

                    stream.write(raw)
                    sendqueue.task_done()
            except Empty:
                pass
            
    def send_rtcm(self, rtcm):
        try:
            self.sendqueue.put((rtcm, None))
        except Exception as e:
            if self.verbose:
                logger.error(f"Error sending RTCM data: {e}")
            
    def get_nav_data(self):
        if len(self.nav_pvt_queue) > 0:
            try:
                parsed_data = self.nav_pvt_queue.pop()
                if hasattr(parsed_data, "lat") \
                    and hasattr(parsed_data, "lon") \
                    and hasattr(parsed_data, "hMSL") \
                    and hasattr(parsed_data, "carrSoln") \
                    and hasattr(parsed_data, "fixType") \
                    and hasattr(parsed_data, "gnssFixOk"):
                        
                    lat = parsed_data.lat
                    lon = parsed_data.lon
                    alt = parsed_data.hMSL / 1000 # mm to m
                    carr_soln = parsed_data.carrSoln
                    fix_type = parsed_data.fixType
                    gnss_fix_ok = parsed_data.gnssFixOk
                    
                    return (lat, lon, alt, carr_soln, fix_type, gnss_fix_ok)
            except Empty:
                pass
        return None
        
    
                    
    def config(self):
        
        # disable UART1, UART2, only enable USB
        layers = 1
        transaction = 0
        cfg_data = []
        for port_type in ("UART1", "UART2"):
            cfg_data.append((f"CFG_{port_type}_ENABLED", False))
        
        # config USB
        for port_type in ("USB",):
            cfg_data.append((f"CFG_{port_type}_ENABLED", True))
            cfg_data.append((f"CFG_{port_type}OUTPROT_RTCM3X", False))  
            
        msg = UBXMessage.config_set(layers, transaction, cfg_data)
        self.sendqueue.put((msg.serialize(), msg))

        self.enable_out_ubx(self.enableubx)
        self.enable_out_nmea(self.enablenmea)
        self.enable_in_rtcm(True)
        
        layers = 1
        transaction = 0
        cfg_data = [] 
        # config Dynamic Model as automotive
        cfg_data.append(("CFG_NAVSPG_DYNMODEL", 4)) # 4 = automotive
        msg = UBXMessage.config_set(layers, transaction, cfg_data)
        self.sendqueue.put((msg.serialize(), msg))

        layers = 1
        transaction = 0
        cfg_data = [] 
        # cfg rate
        cfg_data.append(("CFG_RATE_MEAS", self.measrate))
        cfg_data.append(("CFG_RATE_NAV", self.navrate))
        cfg_data.append(("CFG_RATE_NAV_PRIO", self.navpriorate))
        msg = UBXMessage.config_set(layers, transaction, cfg_data)
        self.sendqueue.put((msg.serialize(), msg))
        

    def enable_in_rtcm(self, enable: bool):
        """
        Enable RTCM input.
        :param bool enable: enable RTCM
        """
        layers = 1
        transaction = 0
        cfg_data = []
        for port_type in ("USB",):
            cfg_data.append((f"CFG_{port_type}INPROT_RTCM3X", enable))

        msg = UBXMessage.config_set(layers, transaction, cfg_data)
        self.sendqueue.put((msg.serialize(), msg))
        
    
    def enable_out_nmea(self, enable: bool):
        """
        Enable NMEA output (only GGA).
        :param bool enable: enable NMEA
        """
        layers = 1
        transaction = 0
        cfg_data = []
        for port_type in ("USB",):
            cfg_data.append((f"CFG_{port_type}OUTPROT_NMEA", enable))
            cfg_data.append((f"CFG_MSGOUT_NMEA_ID_GGA_{port_type}", enable))

            # suppress all common NMEA messages on the specified port
            cfg_data.append((f"CFG_MSGOUT_NMEA_ID_GLL_{port_type}", False))
            cfg_data.append((f"CFG_MSGOUT_NMEA_ID_GSA_{port_type}", False))
            cfg_data.append((f"CFG_MSGOUT_NMEA_ID_GSV_{port_type}", False))
            cfg_data.append((f"CFG_MSGOUT_NMEA_ID_RMC_{port_type}", False))
            cfg_data.append((f"CFG_MSGOUT_NMEA_ID_VTG_{port_type}", False))
            cfg_data.append((f"CFG_MSGOUT_NMEA_ID_ZDA_{port_type}", False))
            cfg_data.append((f"CFG_MSGOUT_NMEA_ID_GST_{port_type}", False))
            cfg_data.append((f"CFG_MSGOUT_NMEA_ID_GNS_{port_type}", False))

        msg = UBXMessage.config_set(layers, transaction, cfg_data)
        self.sendqueue.put((msg.serialize(), msg))
        

    def enable_out_ubx(self, enable: bool):
        """
        Enable UBX output (only NAV-PVT).
        :param bool enable: enable UBX
        """

        layers = 1
        transaction = 0
        cfg_data = []
        for port_type in ("USB",):
            cfg_data.append((f"CFG_{port_type}OUTPROT_UBX", enable))
            cfg_data.append((f"CFG_MSGOUT_UBX_NAV_PVT_{port_type}", enable))
            cfg_data.append((f"CFG_MSGOUT_UBX_NAV_COV_{port_type}", enable))

        msg = UBXMessage.config_set(layers, transaction, cfg_data)
        self.sendqueue.put((msg.serialize(), msg))