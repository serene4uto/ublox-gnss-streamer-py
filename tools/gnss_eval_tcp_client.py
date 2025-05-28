import socket
import argparse
import time
import yaml # For YAML configuration
import logging
import pyproj # For UTM conversion
import math
import json
from datetime import datetime, timezone # Added timezone for KST
from pathlib import Path
import threading
from collections import deque

# --- Global ZoneInfo for KST (if available) ---
KST_TZ = None
try:
    from zoneinfo import ZoneInfo
    KST_TZ = ZoneInfo("Asia/Seoul")
    print("[Main] zoneinfo found, KST conversion enabled.")
except ImportError:
    print("[Main] zoneinfo module not found. Timestamps will be in UTC or system local time if KST conversion fails.")
    KST_TZ = timezone.utc # Fallback to UTC if zoneinfo is not available

# --- Console Logger Setup ---
console_logger = logging.getLogger('GNSSClientConsole')
console_logger.setLevel(logging.INFO)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
ch.setFormatter(formatter)
if not console_logger.hasHandlers():
    console_logger.addHandler(ch)

# --- Utility Functions ---
def get_utm_zone(latitude, longitude):
    """
    Calculates the UTM zone number for a given latitude and longitude.
    """
    if not (-80.0 <= latitude <= 84.0):
        raise ValueError("Latitude out of UTM range (-80 to 84 degrees).")
    return math.floor((longitude + 180) / 6) + 1

def format_timestamp_to_kst(utc_timestamp_str):
    """
    Formats a UTC timestamp string (from NMEA or similar) to a KST string.
    Example input: "010203.000" (HHMMSS.sss)
    """
    try:
        # Assuming the input is just HHMMSS.sss and refers to the current date
        # This might need adjustment if the timestamp includes date information
        current_date = datetime.now(timezone.utc).date()
        hour = int(utc_timestamp_str[0:2])
        minute = int(utc_timestamp_str[2:4])
        second = int(utc_timestamp_str[4:6])
        microsecond = int(float(utc_timestamp_str[6:]) * 1_000_000) if '.' in utc_timestamp_str else 0

        dt_utc = datetime(current_date.year, current_date.month, current_date.day,
                          hour, minute, second, microsecond, tzinfo=timezone.utc)

        if KST_TZ and KST_TZ != timezone.utc : # Check if KST_TZ is successfully loaded
            dt_kst = dt_utc.astimezone(KST_TZ)
            return dt_kst.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] # Milliseconds
        else:
            return dt_utc.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] + " UTC" # Indicate UTC if KST not available
    except Exception as e:
        console_logger.error(f"[Util] Error formatting timestamp '{utc_timestamp_str}': {e}")
        return utc_timestamp_str # Return original on error

def evaluate_data(json_str, gt_latitude, gt_longitude):
    """
    Processes a JSON string, extracts GNSS data, and calculates errors.
    """
    try:
        data = json.loads(json_str)
        if not isinstance(data, dict):
            console_logger.warning(f"[Evaluate] Parsed JSON is not a dictionary: {json_str}")
            return None

        msg_time = data.get('timestamp', 'N/A') # Timestamp from message, if available
        lat = data.get('lat')
        lon = data.get('lon')
        fix_type = data.get('type', 'N/A') # e.g., 'GGA_FIX_RTK_FIXED', 'GGA_FIX_INVALID'
        
        # if msg_time != 'N/A':
        #     # If timestamp is in HHMMSS.sss format, convert to KST
        #     if isinstance(msg_time, str) and len(msg_time) >= 6:
        #         msg_time = format_timestamp_to_kst(msg_time)
        #     else:
        #         msg_time = format_timestamp_to_kst(str(msg_time))

        if lat is None or lon is None:
            console_logger.warning(f"[Evaluate] Missing lat/lon in data: {json_str}")
            return None

        # Convert lat/lon to float
        try:
            lat = float(lat)
            lon = float(lon)
        except ValueError:
            console_logger.warning(f"[Evaluate] Invalid lat/lon format in data: {json_str}")
            return None

        # Calculate UTM zone and create a PyProj transformer
        utm_zone = get_utm_zone(lat, lon)
        transformer = pyproj.Proj(proj='utm', zone=utm_zone, ellps='WGS84', south=lat < 0)

        # Transform current and ground truth coordinates to UTM
        easting, northing = transformer(lon, lat)
        gt_easting, gt_northing = transformer(gt_longitude, gt_latitude)

        # Calculate errors
        northing_error = northing - gt_northing
        easting_error = easting - gt_easting
        horizontal_error_2d = math.sqrt(northing_error**2 + easting_error**2) # This is often same as hpe from receiver if fix is good.

        processed_info = {
            "timestamp": msg_time, #format_timestamp_to_kst(msg_time),
            "lat": lat,
            "lon": lon,
            "fix_type": str(fix_type),
            "hpe": horizontal_error_2d, # Horizontal Position Error (HPE) in meters
            "northing_error": northing_error,
            "easting_error": easting_error,
        }
        return processed_info

    except json.JSONDecodeError:
        console_logger.error(f"[Evaluate] Invalid JSON string: {json_str}")
        return None
    except ValueError as ve: # For errors from get_utm_zone or float conversion
        console_logger.error(f"[Evaluate] Value error processing data: {ve} for input {json_str}")
        return None
    except Exception as e:
        console_logger.error(f"[Evaluate] Unexpected error processing data: {e} for input {json_str}", exc_info=True)
        return None

# --- Receiver Thread Function ---
def receiver_thread_func(
    host,
    port,
    shared_deque,
    lock,
    stop_event
):
    console_logger.info(f"[Receiver] Thread started. Attempting to connect to {host}:{port}.")
    data_buffer = b""
    sock = None
    msg_rate = None
    msg_prev_time = []
    alpha = 0.2  # Smoothing factor for EMA

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
        console_logger.info(f"[Receiver] Successfully connected to server at {host}:{port}.")
        sock.settimeout(0.1) # Short timeout for non-blocking recv

        while not stop_event.is_set():
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    console_logger.info("[Receiver] Server closed connection.")
                    break
                data_buffer += chunk
            except socket.timeout:
                # This is expected if no data is received within the timeout
                # Check stop_event again to allow quick exit if flagged
                if stop_event.is_set():
                    break
                continue # Go back to recv
            except socket.error as e:
                console_logger.error(f"[Receiver] Socket error: {e}")
                break 

            # Calculate message rate
            current_time = time.time()
            msg_prev_time.append(current_time)

            if len(msg_prev_time) > 10: # Keep window of last 10 message arrival times
                msg_prev_time.pop(0)

            if len(msg_prev_time) >= 2:
                time_diff = current_time - msg_prev_time[0]
                if time_diff > 0:
                    current_rate_calc = len(msg_prev_time) / time_diff
                    if msg_rate is None:
                        msg_rate = current_rate_calc
                    else:
                        # Exponential Moving Average (EMA)
                        msg_rate = alpha * current_rate_calc + (1 - alpha) * msg_rate

            # Process messages in buffer
            while b'\n' in data_buffer:
                if stop_event.is_set():
                    break
                message_bytes, data_buffer = data_buffer.split(b'\n', 1)
                try:
                    msg_str_decoded = message_bytes.decode('utf-8', errors='replace').strip()
                    if msg_str_decoded:
                        with lock:
                            shared_deque.append((msg_str_decoded, msg_rate))
                except UnicodeDecodeError as ude:
                    console_logger.warning(f"[Receiver] Unicode decode error: {ude}. Message part: {message_bytes[:50]}")
                except Exception as e_decode:
                    console_logger.error(f"[Receiver] Error decoding/queueing message: {e_decode}")


    except ConnectionRefusedError:
        console_logger.error(f"[Receiver] Connection refused to {host}:{port}.")
    except socket.gaierror:
        console_logger.error(f"[Receiver] Address-related error connecting to {host}:{port} (e.g., host not found).")
    except Exception as e:
        console_logger.error(f"[Receiver] Unexpected error: {e}", exc_info=True)
    finally:
        console_logger.info("[Receiver] Thread stopping...")
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR) # Gracefully close
            except OSError:
                pass 
            sock.close()
        if not stop_event.is_set():
             stop_event.set() 
        console_logger.info("[Receiver] Thread finished.")


# --- Processor Thread Function ---
def processor_thread_func(
    shared_deque,
    lock,
    eval_hz,
    gt_lat,
    gt_lon,
    log_enable_flag,
    log_file_path,
    stop_event
):
    console_logger.info("[Processor] Thread started.")

    log_file_handle = None
    if log_enable_flag and log_file_path:
        try:
            Path(log_file_path).parent.mkdir(parents=True, exist_ok=True)
            log_file_handle = open(log_file_path, 'w', encoding='utf-8', newline='')
            # Write header to log file
            header = "TimestampKST,Latitude,Longitude,FixType,HPE(m),NorthingError(m),EastingError(m),MessageRate(Hz)\n"
            log_file_handle.write(header)
            log_file_handle.flush() # Ensure header is written
            console_logger.info(f"[Processor] Logging report data lines to '{log_file_path}' enabled.")
        except IOError as e:
            console_logger.error(f"[Processor] Failed to open log file {log_file_path}: {e}")
            log_file_handle = None # Ensure it's None if open fails

    report_interval_seconds = 1.0 / eval_hz if eval_hz > 0 else float('inf') # Avoid division by zero
    if report_interval_seconds == float('inf'):
        console_logger.warning("[Processor] eval_hz is zero or invalid, processor will not report periodically.")


    while not stop_event.is_set():
        # Wait for the report interval or until stop_event is set
        if report_interval_seconds != float('inf') and stop_event.wait(report_interval_seconds):
            break # Stop event was set

        msg_str_from_q = None
        msg_rate_from_q = None
        processed_info = None

        with lock:
            if shared_deque:
                data = shared_deque.popleft()
                msg_str_from_q = data[0]
                msg_rate_from_q = data[1]

        if msg_str_from_q: # Check if a message was actually popped
            processed_info = evaluate_data(msg_str_from_q, gt_lat, gt_lon)


        # --- Constructing report string and data fields ---
        report_data_fields_list = []
        console_report_str_parts = []

        if processed_info:
            ts_kst = processed_info.get('timestamp', "N/A")
            lat_str = f"{processed_info.get('lat', 0.0):.6f}" if processed_info.get('lat') is not None else "N/A"
            lon_str = f"{processed_info.get('lon', 0.0):.6f}" if processed_info.get('lon') is not None else "N/A"
            fix_type = str(processed_info.get('fix_type', "N/A"))
            hpe_str = f"{processed_info.get('hpe', 99.99):.2f}" if processed_info.get('hpe') is not None else "N/A"
            n_err_str = f"{processed_info.get('northing_error', 0.0):.2f}" if processed_info.get('northing_error') is not None else "N/A"
            e_err_str = f"{processed_info.get('easting_error', 0.0):.2f}" if processed_info.get('easting_error') is not None else "N/A"

            report_data_fields_list = [
                ts_kst, lat_str, lon_str, fix_type, hpe_str, n_err_str, e_err_str,
                f"{msg_rate_from_q:.2f}" if msg_rate_from_q is not None else "N/A"
            ]
            console_report_str_parts = [
                f"TS_KST:{ts_kst}", f"Lat:{lat_str}", f"Lon:{lon_str}", f"Type:{fix_type}",
                f"HPE:{hpe_str}m", f"N_Err:{n_err_str}m", f"E_Err:{e_err_str}m",
                f"MsgRate:{f'{msg_rate_from_q:.2f}' if msg_rate_from_q is not None else 'N/A'}msg/s"
            ]
        else: # No valid processed_info (either no message from queue, or evaluate_data returned None)
            current_rate_str = f"{msg_rate_from_q:.2f}" if msg_rate_from_q is not None else "N/A"
            report_data_fields_list = ["N/A"] * 7 + [current_rate_str] # 7 N/A fields + rate
            console_report_str_parts = [f"MsgRate:{current_rate_str}msg/s", "(No valid GNSS data for this interval)"]


        console_logger.info(f"CONSOLE_REPORT | {' | '.join(console_report_str_parts)} (Report @ {eval_hz}Hz)")

        if log_file_handle:
            try:
                log_file_handle.write(','.join(map(str, report_data_fields_list)) + "\n")
                log_file_handle.flush() # Ensure data is written to disk periodically
            except Exception as e_log_file:
                console_logger.error(f"[Processor] Error writing to log file: {e_log_file}")
                # Consider closing the file or re-opening if errors persist

        if report_interval_seconds == float('inf') and stop_event.is_set(): # If eval_hz was 0, we need another way to break
            break


    console_logger.info("[Processor] Stop event received or loop finished.")
    if log_file_handle:
        try:
            log_file_handle.close()
            console_logger.info(f"[Processor] Closed log file: {log_file_path}")
        except Exception as e_close:
            console_logger.error(f"[Processor] Error closing log file: {e_close}")
    console_logger.info("[Processor] Thread finished.")

# --- Argument Parser Setup ---
def parse_args():
    parser = argparse.ArgumentParser(
        description="GNSS TCP Client for Evaluating GNSS Data Stream",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter # Shows default values in help
    )
    parser.add_argument('--yaml-config', type=str, default=None,
                        help='Path to YAML configuration file. CLI arguments will override YAML settings.')
    # TCP settings
    pgroup_tcp = parser.add_argument_group('TCP Server Connection')
    pgroup_tcp.add_argument('--tcp-host', type=str, help='Server IP address (overrides YAML/default)')
    pgroup_tcp.add_argument('--tcp-port', type=int, help='Server port (overrides YAML/default)')

    # Evaluation settings
    pgroup_eval = parser.add_argument_group('Evaluation Parameters')
    pgroup_eval.add_argument('--eval-hz', type=float, help='Processor thread reporting rate in Hz (overrides YAML/default)')
    pgroup_eval.add_argument('--gt-lat', type=float, help='Ground truth latitude (overrides YAML/default)')
    pgroup_eval.add_argument('--gt-lon', type=float, help='Ground truth longitude (overrides YAML/default)')

    # Logging settings
    pgroup_log = parser.add_argument_group('Logging Configuration')
    pgroup_log.add_argument('--log-enable', action=argparse.BooleanOptionalAction, default=None,
                        help='Enable logging of report data lines. Use --log-enable or --no-log-enable. Overrides YAML if present.')
    pgroup_log.add_argument('--log-file', type=str, default=None,
                        help='File to log report data lines. Overrides YAML. If --log-enable is used and this is not set (and not in YAML), a default name is generated.')
    return parser.parse_args()

# --- Main Function ---
def main():
    args = parse_args()

    # 1. Set base default configuration (used if not in YAML and not in CLI)
    config = {
        'tcp_host': '127.0.0.1',
        'tcp_port': 50012,
        'eval_hz': 1.0,
        'gt_lat': 36.116588, # Example: Gumi City Hall
        'gt_lon': 128.364695, # Example: Gumi City Hall
        'log_enable': False,
        'log_file': None, # Default to None, will be auto-generated if enabled and not specified
    }
    console_logger.info(f"[Main] Initial default config: {config}")

    # 2. Load and merge YAML configuration if a path is provided
    if args.yaml_config:
        try:
            with open(args.yaml_config, 'r', encoding='utf-8') as f:
                yaml_data = yaml.safe_load(f)
                if yaml_data:
                    console_logger.info(f"[Main] Loading configuration from YAML file: {args.yaml_config}")
                    # TCP settings
                    tcp_settings = yaml_data.get('tcp', {})
                    if tcp_settings.get('host') is not None: config['tcp_host'] = tcp_settings['host']
                    if tcp_settings.get('port') is not None: config['tcp_port'] = tcp_settings['port']
                    # Evaluation settings
                    eval_settings = yaml_data.get('evaluation', {})
                    if eval_settings.get('rate_hz') is not None: config['eval_hz'] = eval_settings['rate_hz']
                    # Ground truth settings
                    gt_settings = yaml_data.get('ground_truth', {})
                    if gt_settings.get('latitude') is not None: config['gt_lat'] = gt_settings['latitude']
                    if gt_settings.get('longitude') is not None: config['gt_lon'] = gt_settings['longitude']
                    # Logging settings
                    log_settings = yaml_data.get('logging', {})
                    if log_settings.get('enable') is not None: config['log_enable'] = log_settings['enable']
                    if log_settings.get('file_path') is not None: config['log_file'] = log_settings['file_path']
                    console_logger.info(f"[Main] Config after YAML load: {config}")
                else:
                    console_logger.warning(f"[Main] YAML config file {args.yaml_config} is empty or invalid. Using defaults and/or CLI args.")
        except FileNotFoundError:
            console_logger.warning(f"[Main] YAML config file not found: {args.yaml_config}. Using defaults and/or CLI args.")
        except yaml.YAMLError as e:
            console_logger.error(f"[Main] Error parsing YAML config file {args.yaml_config}: {e}. Using defaults and/or CLI args.")
        except Exception as e:
            console_logger.error(f"[Main] Unexpected error loading YAML config {args.yaml_config}: {e}", exc_info=True)


    # 3. Override with Command Line Arguments (CLI has highest precedence)
    cli_args_provided = vars(args)
    if cli_args_provided.get('tcp_host') is not None: config['tcp_host'] = cli_args_provided['tcp_host']
    if cli_args_provided.get('tcp_port') is not None: config['tcp_port'] = cli_args_provided['tcp_port']
    if cli_args_provided.get('eval_hz') is not None: config['eval_hz'] = cli_args_provided['eval_hz']
    if cli_args_provided.get('gt_lat') is not None: config['gt_lat'] = cli_args_provided['gt_lat']
    if cli_args_provided.get('gt_lon') is not None: config['gt_lon'] = cli_args_provided['gt_lon']
    # Handle log_enable (BooleanOptionalAction means args.log_enable can be True, False, or None)
    if args.log_enable is not None: # If --log-enable or --no-log-enable was used
        config['log_enable'] = args.log_enable
    if cli_args_provided.get('log_file') is not None: config['log_file'] = cli_args_provided['log_file']

    console_logger.info(f"[Main] Config after CLI override: {config}")

    # Automatic log file naming if enabled but no file path is set
    if config['log_enable'] and config['log_file'] is None:
        log_dir_name = ".gnss_log"
        log_dir = Path(log_dir_name)
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            # Generate filename with current timestamp and relevant config info
            current_time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            dynamic_filename = f"gnss_eval_{config['tcp_host']}_{config['tcp_port']}_{current_time_str}.csv"
            config['log_file'] = str(log_dir / dynamic_filename)
            console_logger.info(f"[Main] Logging enabled and --log-file not specified, using default: {config['log_file']}")
        except Exception as e_mkdir:
            console_logger.error(f"[Main] Failed to create log directory {log_dir_name} or default log file name: {e_mkdir}. Disabling logging.")
            config['log_enable'] = False
            config['log_file'] = None

    # Final check: if logging is enabled but file path is still None (should not happen with above logic)
    if config['log_enable'] and config['log_file'] is None:
        console_logger.error("[Main] Logging is enabled, but no log file path could be determined. Disabling logging.")
        config['log_enable'] = False


    final_log_enable_flag = config['log_enable']
    final_log_file_path = config['log_file']

    console_logger.info(
        f"[Main] Final effective configuration: \n"
        f"  TCP Host: {config['tcp_host']}\n"
        f"  TCP Port: {config['tcp_port']}\n"
        f"  Report Rate: {config['eval_hz']} Hz\n"
        f"  GT Latitude: {config['gt_lat']}\n"
        f"  GT Longitude: {config['gt_lon']}\n"
        f"  Logging Enabled: {final_log_enable_flag}\n"
        f"  Log File Path: {final_log_file_path if final_log_enable_flag else 'N/A'}"
    )

    if config['eval_hz'] <= 0:
        console_logger.warning("[Main] eval_hz is non-positive. Processor thread will process messages as they arrive but console/log reporting interval will be effectively infinite (or very slow based on wait timeout).")


    # --- Shared Resources & Threads ---
    shared_message_deque = deque(maxlen=200) # Max length to prevent unbounded memory growth if processor is slow
    deque_lock = threading.Lock()
    stop_event = threading.Event()

    receiver = threading.Thread(target=receiver_thread_func,
                                args=(config['tcp_host'], config['tcp_port'],
                                      shared_message_deque, deque_lock,
                                      stop_event),
                                name="ReceiverThread")
    processor = threading.Thread(target=processor_thread_func,
                                 args=(shared_message_deque, deque_lock,
                                       config['eval_hz'], config['gt_lat'], config['gt_lon'],
                                       final_log_enable_flag, final_log_file_path,
                                       stop_event),
                                 name="ProcessorThread")

    # Daemon threads will exit when the main program exits
    receiver.daemon = True
    processor.daemon = True

    console_logger.info("[Main] Starting threads...")
    receiver.start()
    processor.start()

    try:
        # Keep main thread alive while worker threads are running
        # Or implement more sophisticated monitoring/control logic
        while not stop_event.is_set() and receiver.is_alive() and processor.is_alive():
            time.sleep(1.0) # Check periodically

        # If stop_event was set by one of the threads (e.g., receiver connection closed)
        if stop_event.is_set():
            console_logger.info("[Main] Stop event detected. Initiating shutdown.")
        elif not receiver.is_alive():
            console_logger.warning("[Main] Receiver thread exited unexpectedly. Signaling stop.")
            if not stop_event.is_set(): stop_event.set()
        elif not processor.is_alive():
            console_logger.warning("[Main] Processor thread exited unexpectedly. Signaling stop.")
            if not stop_event.is_set(): stop_event.set()


    except KeyboardInterrupt:
        console_logger.info("[Main] Ctrl+C received. Signaling threads to stop...")
        if not stop_event.is_set():
            stop_event.set()
    except Exception as e_main:
        console_logger.error(f"[Main] An unexpected error occurred in the main loop: {e_main}", exc_info=True)
        if not stop_event.is_set():
            stop_event.set()
    finally:
        console_logger.info("[Main] Shutdown sequence initiated...")

        if not stop_event.is_set(): # Ensure stop_event is set if not already
            stop_event.set()

        console_logger.info("[Main] Waiting for Receiver thread to join (timeout 2s)...")
        receiver.join(timeout=2.0)
        if receiver.is_alive():
            console_logger.warning("[Main] Receiver thread did not join in time.")

        console_logger.info("[Main] Waiting for Processor thread to join (timeout 5s)...")
        processor.join(timeout=5.0) # Processor might be writing to file
        if processor.is_alive():
            console_logger.warning("[Main] Processor thread did not join in time.")

        console_logger.info("[Main] Application finished.")


if __name__ == '__main__':
    main()
