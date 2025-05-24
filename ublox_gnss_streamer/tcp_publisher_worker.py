import threading
from threading import Event
import socket

from .tcp_publisher import TcpPublisher
from ublox_gnss_streamer.utils.logger import logger
from ublox_gnss_streamer.utils.threadsafe_deque import ThreadSafeDeque

class TcpPublisherWorker:
    def __init__(
        self, 
        publisher: TcpPublisher, 
        stop_event: Event,
        gnss_queue: ThreadSafeDeque = None,
    ):
        self.publisher = publisher
        self.gnss_queue = gnss_queue
        self.stop_event = stop_event
        self.publisher_lock = threading.Lock()
        self.accept_thread = None
        self.broadcast_thread = None
    
    def run(self):
        self.publisher.start_server()
        self.accept_thread = threading.Thread(target=self._accept_clients_loop, daemon=True)
        self.accept_thread.start()
        self.broadcast_thread = threading.Thread(target=self._broadcast_data_loop, daemon=True)
        self.broadcast_thread.start()
        logger.info("TCP Publisher worker started.")
        return True
    
    def _accept_clients_loop(self):
        while not self.stop_event.is_set():
            try:
                self.publisher.server_socket.settimeout(1.0)
                try:
                    self.publisher.accept_client()
                except socket.timeout:
                    continue
                with self.publisher_lock:
                    self.publisher.refresh_clients()
            except Exception as e:
                logger.error(f"Error accepting client: {e}", exc_info=True)
    
    def _broadcast_data_loop(self):
        while not self.stop_event.is_set():
            try:
                data = self.gnss_queue.popleft()  # thread-safe pop
            except IndexError:
                # Buffer is empty, wait a bit
                threading.Event().wait(0.001)
                continue
            if data is not None:
                with self.publisher_lock:
                    self.publisher.send_to_all(data)
    
    def stop(self):
        self.stop_event.set()
        if self.accept_thread:
            self.accept_thread.join()
        if self.broadcast_thread:
            self.broadcast_thread.join()
        with self.publisher_lock:
            self.publisher.stop_server()
        logger.info("TCP Publisher worker stopped.")
        
