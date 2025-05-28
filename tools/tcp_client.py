import socket
import argparse
import time

def main():
    parser = argparse.ArgumentParser(description="Simple TCP client for GNSS data with message rate display.")
    parser.add_argument('--host', type=str, default='127.0.0.1', help='Server IP address (default: 127.0.0.1)')
    parser.add_argument('--port', type=int, default=50012, help='Server port (default: 50012)')
    parser.add_argument('--rate-interval', type=float, default=1.0, help='Interval (seconds) to display message rate (default: 1.0)')
    args = parser.parse_args()

    HOST = args.host
    PORT = args.port
    RATE_INTERVAL = args.rate_interval

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((HOST, PORT))
            print(f"Connected to server at {HOST}:{PORT}.")

            msg_count = 0
            start_time = time.time()

            while True:
                data = s.recv(4096)
                if not data:
                    print("Server closed connection.")
                    break
                print("Received:", data.decode('utf-8').strip())
                msg_count += 1

                elapsed = time.time() - start_time
                if elapsed >= RATE_INTERVAL:
                    rate = msg_count / elapsed
                    print(f"Message rate: {rate:.2f} messages/sec")
                    msg_count = 0
                    start_time = time.time()

    except ConnectionRefusedError:
        print("Connection refused. Ensure the server is running and the host/port are correct.")
    except KeyboardInterrupt:
        print("Client stopped by user.")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == '__main__':
    main()
