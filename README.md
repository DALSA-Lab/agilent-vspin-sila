# Agilent VSpin & Access2 Loader - SiLA 2 Server

This repository provides a SiLA 2 server and a standalone Python driver for the **Agilent VSpin Centrifuge** and its integrated **Access2 plate loader**.

This integration was developed to provide an independent, cross-platform interface for interoperability with the instrument. The protocol implementation was achieved through communication monitoring and analysis of the serial interface, building upon foundational protocol insights initially published by the open-source PyLabRobot project.

## Repository Structure

- `feature_definitions/`: The SiLA 2 Feature Definition (`.sila.xml`) for the VSpin Controller.
- `vspin_driver/`: The standalone, low-level Python API for interacting with the centrifuge and loader via RS-232.
- `vspin_sila/`: The SiLA 2 server implementation and generated gRPC components.
- `examples/`: Utility scripts for calibration and running the server locally.

## Requirements

- Python 3.8+
- Two RS-232 Serial connections to the host PC (one for the Centrifuge, one for the Access2 Loader).

## Installation

Install the package and its dependencies in editable mode:

```bash
python -m pip install -e .
```

## Hardware Calibration (One-Time Setup)

The centrifuge requires a calibration offset to ensure the rotor perfectly aligns with the plate loader. 

1. Ensure your hardware is connected.
2. Run the interactive calibration script:
   ```bash
   python examples/calibrate_centrifuge.py
   ```
3. Follow the on-screen instructions to manually align the bucket. The script will output a **Calibration Offset** integer (e.g., `5198`). Note this number down.

## Running the SiLA Server

To start the SiLA 2 server, use the package entry point and provide the COM ports and calibration offset:

**On Windows:**
```powershell
python -m vspin_sila --centrifuge-com-port COM15 --loader-com-port COM13 --calibration-offset 5198 --insecure
```

**On Linux:**
```bash
python -m vspin_sila --centrifuge-com-port /dev/ttyUSB1 --loader-com-port /dev/ttyUSB0 --calibration-offset 5198 --insecure
```

Use the `--help` flag for a full list of available server arguments.