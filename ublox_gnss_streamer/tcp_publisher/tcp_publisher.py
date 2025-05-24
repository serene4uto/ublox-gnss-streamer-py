import socket
import threading
from queue import Queue

from ublox_gnss_streamer.utils.logger import logger

class TcpPublisher:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.server_socket = None
        self.clients = []

    def start_server(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)

    def accept_client(self):
        client, addr = self.server_socket.accept()
        self.clients.append(client)
        print(f"Client connected: {addr}")

    def send_to_all(self, data):
        for client in self.clients[:]:
            try:
                client.sendall(data)
            except Exception:
                self.clients.remove(client)