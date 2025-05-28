# Ublox GNSS Streamer

This repository contains the **source code** and **binary build script** for the Ublox GNSS Streamer.

This software configures the Ublox GNSS module, collects GNSS data, connects to an NTRIP caster/server to receive RTCM correction data, and supplies it to the GNSS module for Real-Time Kinematic (RTK) positioning.

The collected GNSS data is streamed over TCP for client consumption. Additionally, a linear extrapolation method is applied to the GNSS data to increase the effective data rate and improve temporal resolution.

Key features include:
- Ublox GNSS module configuration and data acquisition
- NTRIP client support for RTCM correction data
- Real-time GNSS data streaming over TCP
- Support for multiple concurrent TCP clients
- Linear extrapolation for GNSS data rate enhancement

This project is ideal for applications demanding real-time, high-precision GNSS data streaming and advanced processing capabilities.

## Prerequisites

Before getting started, ensure the system meets the following requirements based on the chosen usage method.

### For Running Pre-compiled Binaries

*   **Operating System:** A Linux-based system compatible with the target architecture (`aarch64` for ARM64 systems, or `x86_64` for 64-bit Intel/AMD systems).
*   **Standard Utilities:** Basic command-line utilities such as `tar` and `gzip` for extracting the downloaded archive.
*   **Permissions:** Ability to make the downloaded binary executable (`chmod +x`).

### For Running from Source / Development

*   **Python:** Python 3.8 or newer. It is recommended to use a virtual environment (e.g., `venv`, `conda`).
*   **pip:** The Python package installer, used to manage project dependencies. This usually comes with Python.
*   **git:** Required for cloning the repository from GitHub.
*   **Project Dependencies:** As listed in `requirements.txt`. These can be installed using pip.
*   **Operating System:** The Python codebase is generally cross-platform (Linux, macOS, Windows), but specific hardware interactions (like serial port access) might have OS-dependent behavior or naming conventions (e.g., `/dev/ttyUSB0` vs. `COM3`).

## Running from Pre-compiled Binary

For users who prefer not to build from source, pre-compiled binaries are available for download for `aarch64` (ARM64) and `x86_64` (AMD64/Intel64) architectures from the [GitHub Releases page](https://github.com/serene4uto/ublox-gnss-streamer-py/releases/latest).

### 1. Download the Binary

The appropriate binary can be downloaded either directly from the [**Releases page**](https://github.com/serene4uto/ublox-gnss-streamer-py/releases/latest) using a web browser, or via the command line using `wget` or `curl`.

**To download via the command line:**

Identify the correct architecture (`aarch64` or `x86_64`) and the release `[version]` (e.g., `v0.1.0`). The `[version]` corresponds to the release tag.

*   **For `aarch64` (ARM64) architecture:**
    *   Using `wget`:
        ```
        wget https://github.com/serene4uto/ublox-gnss-streamer-py/releases/download/[version]/ublox_gnss_streamer_aarch64-[version].tar.gz
        ```
    *   Using `curl`:
        ```
        curl -L -o ublox_gnss_streamer_aarch64-[version].tar.gz https://github.com/serene4uto/ublox-gnss-streamer-py/releases/download/[version]/ublox_gnss_streamer_aarch64-[version].tar.gz
        ```

*   **For `x86_64` (AMD64/Intel64) architecture:**
    *   Using `wget`:
        ```
        wget https://github.com/serene4uto/ublox-gnss-streamer-py/releases/download/[version]/ublox_gnss_streamer_x86_64-[version].tar.gz
        ```
    *   Using `curl`:
        ```
        curl -L -o ublox_gnss_streamer_x86_64-[version].tar.gz https://github.com/serene4uto/ublox-gnss-streamer-py/releases/download/[version]/ublox_gnss_streamer_x86_64-[version].tar.gz
        ```

**Example (downloading v0.1.0 for x86_64):**
```
wget https://github.com/serene4uto/ublox-gnss-streamer-py/releases/download/v0.1.0/ublox_gnss_streamer_x86_64-v0.1.0.tar.gz
```

or
```
curl -L -o ublox_gnss_streamer_x86_64-v0.1.0.tar.gz https://github.com/serene4uto/ublox-gnss-streamer-py/releases/download/v0.1.0/ublox_gnss_streamer_x86_64-v0.1.0.tar.gz
```

**Manual Download:**
1.  Navigate to the [**Releases page**](https://github.com/serene4uto/ublox-gnss-streamer-py/releases/latest).
2.  Locate the latest release (or the specific version required).
3.  Under the "Assets" section, download the `ublox_gnss_streamer_aarch64-[version].tar.gz` or `ublox_gnss_streamer_x86_64-[version].tar.gz` file corresponding to the target architecture.

### 2. Extract the Binary

Navigate to the directory where the archive was downloaded and extract it. Replace `[filename]` with the name of the downloaded `.tar.gz` file:
```
tar -xzf [filename]
```
For example:
```
tar -xzf ublox_gnss_streamer_x86_64-v0.1.0.tar.gz
```
This will typically create a directory (e.g., `ublox_gnss_streamer_x86_64-v0.1.0`) or extract the files directly into the current folder. The executable will likely be named `ublox_gnss_streamer`.


### 3. Run the Application

After extraction, navigate into the directory containing the executable if one was created:

1.  Make the binary executable (this step is only required once):
    ```
    # If a directory was created, cd into it first, e.g.:
    # cd ublox_gnss_streamer_x86_64-v0.1.0
    chmod +x ublox_gnss_streamer
    ```
2.  Run the application using the executable. Command-line options can be provided to configure its behavior:
    ```
    ./ublox_gnss_streamer [OPTIONS]
    ```
    Common individual options include:

    *   `--serial-port`: Specify the serial port connected to the Ublox GNSS device (e.g., `/dev/ttyUSB0`, `/dev/ttyACM0`).
    *   `--serial-baudrate`: Set the baud rate for serial communication (e.g., `115200`, `460800`).
    *   `--serial-timeout`: Timeout in seconds for serial read operations.
    *   `--serial-interface`: Specify the Ublox module's serial interface being used (e.g., `UART1`, `USB`).
    *   `--ntrip-host`: Hostname or IP address of the NTRIP caster/server.
    *   `--ntrip-port`: Port number of the NTRIP caster/server.
    *   `--ntrip-mountpoint`: Mountpoint name for the NTRIP correction stream.
    *   `--ntrip-username` and `--ntrip-password`: Credentials for NTRIP authentication, if required.
    *   `--tcp-host`: IP address or hostname on which the TCP server will listen (e.g., `0.0.0.0` to listen on all available network interfaces).
    *   `--tcp-port`: Port number for the TCP server to provide the GNSS data stream.
    *   `--logger-level`: Set the logging verbosity level (e.g., `info`, `debug`, `warning`, `error`).

    Alternatively, settings can be grouped in a YAML configuration file and specified using `--config` or `--yaml-config`:
    ```
    ./ublox_gnss_streamer --yaml-config path/to/your_config.yaml
    ```
    An example `config.yaml` might look like this:
    ```
    serial_port: /dev/ttyS0
    serial_baudrate: 38400
    # ... other parameters for ntrip, tcp, logger ...
    ntrip_host: caster.example.com
    tcp_port: 5001
    logger_level: debug
    ```
    (See the "Configuration File" section below for a detailed example and explanations of all YAML parameters.)

**Discovering All Options:**

To view the full list of available command-line options, their descriptions, and default values, run the executable with the `--help` flag:
```
./ublox_gnss_streamer --help
```

**Notes:**
*   Replace `[OPTIONS]` with the actual command-line options suitable for the deployment environment.
*   Ensure that parameters such as the serial port, baudrate, NTRIP credentials, and TCP settings are correctly configured for the specific hardware setup and network environment.
*   Command-line options generally override values set in a configuration file if both are provided.
*   The application can typically be stopped by pressing `Ctrl+C` in the terminal where it is running.

## Running from Source

For users who prefer to run the application directly from the source code, the Ublox GNSS Streamer can be started using its command-line interface (CLI). This method is also suitable for development and testing.

First, ensure the "For Running from Source / Development" prerequisites mentioned in the main [Prerequisites](#prerequisites) section are met. This typically involves:
1.  Cloning the repository:
    ```
    git clone https://github.com/serene4uto/ublox-gnss-streamer-py.git
    ```
2.  Navigating into the project directory:
    ```
    cd ublox-gnss-streamer-py
    ```
3.  Installing project dependencies (it's recommended to do this within a Python virtual environment):
    ```
    # Example: if you have a requirements.txt
    pip install -r requirements.txt
    # Example: if your project uses pyproject.toml for build and dependencies
    # pip install .
    ```

Once the setup is complete, from the root directory of the cloned repository, the Ublox GNSS Streamer can be launched using the following command structure:
```
python -m ublox_gnss_streamer.main [OPTIONS]
```

The available command-line `[OPTIONS]` are the same as those described in the "Run the Application" section for pre-compiled binaries (e.g., `--serial-port`, `--ntrip-host`, `--tcp-port`, etc.).

## Building Binary from Source

To build the binary executable from the source code, run the provided bash script from the root of the project:
```
bash scripts/build-bin.sh
```

After the build completes successfully, the binary file will be available in the `bin` directory within the project root.

This method provides a quick and automated way to compile the project and generate the executable for deployment or testing.

## Example Evaluation Client

To evaluate the GNSS data streamed by `ublox-gnss-streamer-py`, an example client application is available:

**[ublox_gnss_eval_client](https://github.com/serene4uto/ublox_gnss_eval_client)**

This client application currently:
*   Connects to the TCP stream provided by `ublox-gnss-streamer-py`.
*   Evaluates the incoming GNSS message rate (Hz).
*   Calculates the distance error by comparing received positions against a provided ground truth/reference point.
*   Displays evaluation results (message rate, distance error) on the console.
*   Logs the evaluation results to a file for later analysis.

It serves as a practical example of how to build a client to consume, process, and evaluate the data from this streamer.

Please refer to the `ublox_gnss_eval_client` repository for its specific setup and usage instructions.

