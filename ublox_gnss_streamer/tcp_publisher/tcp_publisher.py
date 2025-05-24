import socket

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
        
    def stop_server(self):
        if self.server_socket:
            self.server_socket.close()
            self.server_socket = None
            logger.info("TCP server stopped.")
        for client in self.clients:
            try:
                client.close()
            except Exception as e:
                logger.error(f"Error closing client socket: {e}", exc_info=True)
        self.clients.clear()
        logger.info("All client connections closed.")

    def accept_client(self):
        client, addr = self.server_socket.accept()
        self.clients.append(client)
        logger.info(f"Client connected: {addr}")

    def send_to_all(self, data):
        for client in self.clients[:]:
            try:
                client.sendall(data)
            except Exception as e:
                self.clients.remove(client)
                logger.warning(f"Removed client due to send failure: {e}", exc_info=True)
    
    def refresh_clients(self):
        """Remove closed sockets from the client list."""
        self.clients = [c for c in self.clients if self._is_socket_open(c)]
        logger.debug(f"Active clients refreshed. Current count: {len(self.clients)}")
        
    def _is_socket_open(self, sock):
        try:
            sock.send(b'')
            return True
        except Exception:
            return False