import socket
import argparse
import time
import yaml
import logging # Still used for CONSOLE logging
import pyproj
import math
import json
import csv # Still used for the dedicated --csv-report-file
from datetime import datetime

# Attempt to import ZoneInfo for timezone handling (Python 3.9+)
try:
    from zoneinfo import ZoneInfo
    KST_TZ = ZoneInfo("Asia/Seoul")
except ImportError:
    KST_TZ = None
    pass

# --- CONSOLE Logger Setup ---
console_logger = logging.getLogger(__name__ + "_console")
console_logger.setLevel(logging.INFO)
if console_logger.hasHandlers():
    console_logger.handlers.clear()
console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch = logging.StreamHandler()
ch.setFormatter(console_formatter)
console_logger.addHandler(ch)
# --- End CONSOLE Logger Setup ---


def parse_args():
    parser = argparse.ArgumentParser(
        description="GNSS TCP Client for Evaluating GNSS Data Stream"
    )
    parser.add_argument(
        '--yaml-config', type=str,
        help='Path to YAML configuration file'
    )
    parser.add_argument('--tcp-host', type=str, help='Server IP address')
    parser.add_argument('--tcp-port', type=int, help='Server port')
    parser.add_argument('--eval-hz', type=float, help='Client evaluation and reporting rate in Hz')
    parser.add_argument('--gt-lat', type=float, help='Ground truth latitude')
    parser.add_argument('--gt-lon', type=float, help='Ground truth longitude')
    parser.add_argument('--log-enable', action='store_true',
                        help='Enable logging of ONLY report data lines to --log-file. If --log-file is not specified, a timestamped default name will be used.')
    parser.add_argument('--log-file', type=str, default=None, # Default to None to detect if user provided it
                        help='File to log ONLY report data lines (e.g., data_reports.log). If --log-enable is used and this is not set, a default name like gnss_eval_YYYYMMDD_HHMMSS.log will be generated.')
    parser.add_argument(
        '--csv-report-file', type=str, default=None,
        help='Path to a separate, clean CSV file with header for dedicated evaluation reports (e.g., report.csv)'
    )
    return parser.parse_args()

def get_utm_zone(longitude):
    return int(math.floor((longitude + 180) / 6) % 60) + 1

def format_timestamp_to_kst(timestamp_str_iso):
    if timestamp_str_iso == "N/A":
        return "N/A"
    try:
        dt_aware = datetime.fromisoformat(timestamp_str_iso)
        if KST_TZ:
            dt_kst = dt_aware.astimezone(KST_TZ)
            return dt_kst.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] + " KST"
        else:
            return dt_aware.isoformat()
    except ValueError:
        console_logger.debug(f"Could not parse timestamp '{timestamp_str_iso}' to datetime object.")
        return timestamp_str_iso

def evaluate_data(data_message_str, gt_lat, gt_lon):
    try:
        data_obj = json.loads(data_message_str)
    except json.JSONDecodeError as e:
        console_logger.debug(f"Failed to decode JSON: {e}. Data: '{data_message_str}'")
        return None

    if not isinstance(data_obj, dict):
        console_logger.debug(f"Parsed JSON is not a dictionary. Data: '{data_message_str}'")
        return None

    required_keys = ['lat', 'lon', 'type']
    if not all(key in data_obj for key in required_keys):
        console_logger.debug(f"Essential keys ('lat', 'lon', 'type') missing in JSON. Data: {data_obj}")
        return None

    lat = data_obj['lat']
    lon = data_obj['lon']
    fix_type = data_obj['type']
    raw_timestamp_str = data_obj.get("timestamp", "N/A")
    kst_formatted_timestamp = format_timestamp_to_kst(raw_timestamp_str)

    if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))):
        console_logger.debug(f"Invalid type for lat/lon in JSON. Lat: {lat}, Lon: {lon}")
        return None
    if not isinstance(fix_type, str):
        console_logger.debug(f"Invalid type for 'type' field in JSON. Type: {fix_type}")
        return None

    try:
        utm_zone_data = get_utm_zone(lon)
        wgs84 = pyproj.CRS("EPSG:4326")
        hemisphere = 'north' if lat >= 0 else 'south'
        is_southern_hemisphere = (hemisphere == 'south')
        utm_crs = pyproj.CRS(proj='utm', zone=utm_zone_data, ellps='WGS84', units='m', south=is_southern_hemisphere)
        transformer = pyproj.Transformer.from_crs(wgs84, utm_crs, always_xy=True)

        easting, northing = transformer.transform(lon, lat)
        gt_easting, gt_northing = transformer.transform(gt_lon, gt_lat)

        calculated_hpe = math.sqrt((easting - gt_easting)**2 + (northing - gt_northing)**2)
        easting_error = easting - gt_easting
        northing_error = northing - gt_northing
    except pyproj.exceptions.CRSError as e:
        console_logger.error(f"Pyproj CRS error for lat {lat}, lon {lon}: {e}")
        return None
    except Exception as e:
        console_logger.error(f"Error in UTM conversion/error calculation: {e}")
        return None

    altitude = data_obj.get("alt", "N/A")
    return {
        'timestamp': kst_formatted_timestamp,
        'lat': lat,
        'lon': lon,
        'altitude': altitude,
        'fix_type': fix_type,
        'hpe': calculated_hpe,
        'utm_zone': f"{utm_zone_data}{'N' if hemisphere=='north' else 'S'}",
        'easting': easting,
        'northing': northing,
        'easting_error': easting_error,
        'northing_error': northing_error
    }

def tcp_client(host, port, eval_hz, gt_lat, gt_lon, log_enable_flag, log_file_path_for_reports, csv_report_file_path):
    if log_enable_flag and KST_TZ is None:
        console_logger.warning("zoneinfo module not available. Timestamps in log file might not be explicitly KST formatted if input lacks timezone.")

    data_only_log_file_handle = None
    if log_enable_flag:
        if log_file_path_for_reports: # This path will now be set (either user-defined or dynamically generated)
            try:
                data_only_log_file_handle = open(log_file_path_for_reports, 'w', encoding='utf-8')
                console_logger.info(f"Logging of ONLY report data lines to '{log_file_path_for_reports}' enabled.")
            except IOError as e:
                console_logger.error(f"Failed to open log file {log_file_path_for_reports}: {e}")
                data_only_log_file_handle = None
        else:
            # This case should ideally not be hit if the logic in main() is correct for dynamic filename generation
            console_logger.error("Logging enabled (--log-enable), but log file path is somehow not set. Report data lines will not be logged to a file.")


    dedicated_csv_writer = None
    dedicated_csv_file_handle = None
    dedicated_csv_header = ['Timestamp_KST', 'Latitude', 'Longitude', 'FixType', 'HPE_m', 'NorthingError_m', 'EastingError_m', 'ServerMessageRate_msg_s']
    if csv_report_file_path:
        try:
            dedicated_csv_file_handle = open(csv_report_file_path, 'w', newline='', encoding='utf-8')
            dedicated_csv_writer = csv.writer(dedicated_csv_file_handle)
            dedicated_csv_writer.writerow(dedicated_csv_header)
            console_logger.info(f"Dedicated clean CSV reporting enabled. Reports will be saved to {csv_report_file_path}")
        except IOError as e:
            console_logger.error(f"Failed to open dedicated clean CSV report file {csv_report_file_path}: {e}")
            dedicated_csv_writer = None
            dedicated_csv_file_handle = None

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            console_logger.info(f"Attempting to connect to {host}:{port}...")
            s.connect((host, port))
            console_logger.info(f"Successfully connected to server at {host}:{port}.")

            report_interval_seconds = 1.0 / eval_hz
            s.settimeout(min(report_interval_seconds, 0.1)) 

            data_buffer = b""
            server_messages_received_in_interval = 0
            last_report_time = time.time()
            latest_processed_data_info = None 

            while True:
                try:
                    chunk = s.recv(4096)
                    if not chunk:
                        console_logger.info("Server closed connection.")
                        break
                    data_buffer += chunk
                except socket.timeout:
                    pass
                except socket.error as e:
                    console_logger.error(f"Socket error during recv: {e}")
                    break 

                while b'\n' in data_buffer:
                    message_bytes, data_buffer = data_buffer.split(b'\n', 1)
                    message_str = message_bytes.decode('utf-8', errors='replace').strip()

                    if message_str:
                        server_messages_received_in_interval += 1 
                        processed_info = evaluate_data(message_str, gt_lat, gt_lon)
                        if processed_info:
                            latest_processed_data_info = processed_info
                
                current_time = time.time()
                if current_time - last_report_time >= report_interval_seconds:
                    actual_elapsed_for_report = current_time - last_report_time
                    server_message_rate = server_messages_received_in_interval / actual_elapsed_for_report if actual_elapsed_for_report > 0 else 0.0
                    
                    report_data_fields = []
                    console_report_str_parts = []

                    if latest_processed_data_info:
                        ts_kst = latest_processed_data_info['timestamp']
                        lat_str = f"{latest_processed_data_info['lat']:.6f}"
                        lon_str = f"{latest_processed_data_info['lon']:.6f}"
                        fix_type = latest_processed_data_info['fix_type']
                        hpe_str = f"{latest_processed_data_info['hpe']:.2f}"
                        n_err_str = f"{latest_processed_data_info['northing_error']:.2f}"
                        e_err_str = f"{latest_processed_data_info['easting_error']:.2f}"
                        rate_str = f"{server_message_rate:.2f}"
                        
                        report_data_fields = [ts_kst, lat_str, lon_str, fix_type, hpe_str, n_err_str, e_err_str, rate_str]
                        console_report_str_parts = [f"TS_KST:{ts_kst}", f"Lat:{lat_str}", f"Lon:{lon_str}", f"Type:{fix_type}", 
                                                    f"HPE:{hpe_str}m", f"N_Err:{n_err_str}m", f"E_Err:{e_err_str}m",
                                                    f"SrvRate:{rate_str}msg/s"]
                    else:
                        rate_str = f"{server_message_rate:.2f}"
                        report_data_fields = ["N/A", "N/A", "N/A", "N/A", "N/A", "N/A", "N/A", rate_str]
                        console_report_str_parts = [f"SrvRate:{rate_str}msg/s", "(No valid GNSS data for location)"]
                    
                    print(f"CONSOLE_REPORT | {' | '.join(console_report_str_parts)} (Eval@ {eval_hz}Hz)")

                    if dedicated_csv_writer:
                        try:
                            dedicated_csv_writer.writerow(report_data_fields)
                            if dedicated_csv_file_handle: dedicated_csv_file_handle.flush()
                        except Exception as e_csv:
                            console_logger.error(f"Error writing to dedicated CSV report file: {e_csv}")
                    
                    if data_only_log_file_handle:
                        try:
                            csv_string_for_log_file = ','.join(map(str, report_data_fields))
                            data_only_log_file_handle.write(csv_string_for_log_file + "\n")
                            data_only_log_file_handle.flush()
                        except Exception as e_log_file:
                            console_logger.error(f"Error writing to log file: {e_log_file}")
                    
                    last_report_time = current_time
                    server_messages_received_in_interval = 0
                    latest_processed_data_info = None

                time.sleep(0.001) 

    except ConnectionRefusedError:
        console_logger.error(f"Connection refused. Ensure the server at {host}:{port} is running.")
    except socket.timeout: 
        console_logger.error(f"Socket connection timeout when initially connecting to {host}:{port}.")
    except Exception as e:
        console_logger.error(f"An unexpected error occurred in tcp_client: {e}", exc_info=True)
    finally:
        console_logger.info("TCP client process ending.")
        if dedicated_csv_file_handle:
            try:
                dedicated_csv_file_handle.close()
                console_logger.info(f"Closed dedicated CSV report file: {csv_report_file_path}")
            except Exception as e_close:
                console_logger.error(f"Error closing dedicated CSV report file: {e_close}")
        
        if data_only_log_file_handle:
            try:
                data_only_log_file_handle.close()
                console_logger.info(f"Closed log file: {log_file_path_for_reports}")
            except Exception as e_close:
                 console_logger.error(f"Error closing log file: {e_close}")


def main():
    args = parse_args()
    if KST_TZ is None and (args.log_enable or args.csv_report_file):
        console_logger.warning("zoneinfo module not found. Timestamps might not be explicitly KST.")

    # Initial default config values
    config = {
        'tcp_host': '127.0.0.1',
        'tcp_port': 50012,
        'eval_hz': 1.0, 
        'gt_lat': 36.116588, 
        'gt_lon': 128.364695, 
        'log_enable': False, 
        'log_file': None, # Start with None to detect if user/YAML provides it
        'csv_report_file': None, 
    }

    # 1. Load from YAML if provided (YAML can set log_file)
    if args.yaml_config:
        try:
            with open(args.yaml_config, 'r') as f_yaml:
                yaml_config_data = yaml.safe_load(f_yaml)
                if yaml_config_data: 
                    config.update(yaml_config_data)
            console_logger.info(f"Loaded configuration from YAML file: {args.yaml_config}")
        except FileNotFoundError:
            console_logger.warning(f"YAML config file not found: {args.yaml_config}. Using defaults/CLI args.")
        except Exception as e:
            console_logger.error(f"Failed to load or parse YAML config '{args.yaml_config}': {e}. Using defaults/CLI args.")
    else:
        console_logger.info("No YAML config file provided. Using defaults and/or command-line arguments.")

    # 2. Override with command-line arguments
    # Update log_enable flag first from CLI
    if args.log_enable:
        config['log_enable'] = True
    
    # Update other config values from CLI if they were explicitly provided
    # (argparse defaults to None for non-flag args if not given)
    for arg_name, arg_value in vars(args).items():
        if arg_value is not None: # If CLI argument was provided
            if arg_name == 'log_enable': # Already handled
                continue
            if arg_name in config:
                config[arg_name] = arg_value
            # For csv_report_file, if it's not in config dict initially but in args, add it
            elif arg_name == 'csv_report_file':
                 config[arg_name] = arg_value


    # 3. Generate dynamic log_file name if log_enable is true and log_file is still None
    if config['log_enable'] and config['log_file'] is None:
        current_time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        config['log_file'] = f"gnss_eval_{current_time_str}.log"
        console_logger.info(f"--log-file not specified with --log-enable, using default: {config['log_file']}")


    tcp_host = config['tcp_host']
    tcp_port = config['tcp_port']
    eval_hz = config['eval_hz']
    gt_lat = config['gt_lat']
    gt_lon = config['gt_lon']
    log_enable_flag = config['log_enable']
    log_file_path_for_reports = config.get('log_file') 
    csv_report_file_path = config.get('csv_report_file')

    console_logger.info(f"Final configuration: Host={tcp_host}, Port={tcp_port}, ReportRateHz={eval_hz}, "
                f"GT_Lat={gt_lat}, GT_Lon={gt_lon}, LogReportDataLinesOnlyToFile={log_enable_flag} (to {log_file_path_for_reports}), "
                f"DedicatedCleanCSVReportFile={csv_report_file_path}")

    tcp_client(tcp_host, tcp_port, eval_hz, gt_lat, gt_lon, log_enable_flag, log_file_path_for_reports, csv_report_file_path)
    console_logger.info("Application finished.")


if __name__ == '__main__':
    main()
