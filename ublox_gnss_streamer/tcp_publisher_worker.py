import threading
from threading import Event, Lock
from collections import deque
from .tcp_publisher import TcpPublisher

from ublox_gnss_streamer.utils.logger import logger

class TcpPublisherWorker:
    def __init__(
        self, 
        publisher: TcpPublisher, 
        data_deque: deque,
        data_deque_lock: Lock,
        stop_event: Event,
    ):
        self.publisher = publisher
        self.data_deque = data_deque
        self.data_deque_lock = data_deque_lock
        self.stop_event = stop_event
        self.clients_lock = threading.Lock()
        self.accept_thread = None
        self.broadcast_thread = None

    def start(self):
        self.publisher.start_server()
        self.accept_thread = threading.Thread(target=self._accept_clients, daemon=True)
        self.broadcast_thread = threading.Thread(target=self._broadcast_loop, daemon=True)
        self.accept_thread.start()
        self.broadcast_thread.start()
        logger.info("TcpPublisherWorker started.")

    def _accept_clients(self):
        import socket
        while not self.stop_event.is_set():
            try:
                self.publisher.server_socket.settimeout(1.0)
                try:
                    self.publisher.accept_client()
                except socket.timeout:
                    continue
                with self.clients_lock:
                    self.publisher.clients = type(self.publisher.clients)(
                        c for c in self.publisher.clients if self._is_socket_open(c)
                    )
            except Exception as e:
                logger.error(f"Error accepting client: {e}", exc_info=True)

    def _broadcast_loop(self):
        while not self.stop_event.is_set():
            try:
                with self.data_deque_lock:
                    if self.data_deque:
                        data = self.data_deque.popleft()
                    else:
                        data = None
                if data is not None:
                    with self.clients_lock:
                        clients_snapshot = self.publisher.get_clients_snapshot()
                    dead_clients = []
                    for client in clients_snapshot:
                        try:
                            client.sendall(data)
                        except Exception:
                            dead_clients.append(client)
                    if dead_clients:
                        with self.clients_lock:
                            for dc in dead_clients:
                                self.publisher.remove_client(dc)
                else:
                    threading.Event().wait(0.001)
            except Exception:
                continue

    def _is_socket_open(self, sock):
        try:
            sock.send(b'')
            return True
        except Exception:
            return False

    def stop(self):
        self.stop_event.set()
        if self.accept_thread:
            self.accept_thread.join()
        if self.broadcast_thread:
            self.broadcast_thread.join()
        if self.publisher.server_socket:
            self.publisher.server_socket.close()
        with self.clients_lock:
            for client in self.publisher.clients:
                try:
                    client.close()
                except Exception:
                    pass
        logger.info("TcpPublisherWorker stopped.")
