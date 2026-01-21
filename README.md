# Loop Auto CCV

Automated control and testing system for CCV (Cordon Calibration Value) rig. This project provides Python automation software for testing and analysis with Arduino firmware support.

## Project Structure

```
├── V1/                    # Initial version
├── V2/                    # Second iteration
├── V3/                    # Third version (Linear Testing Only - Stable)
├── V4/                    # In Development (Adds Power Curve Testing)
│   ├── auto_ccv_V4.py
│   ├── auto_ccv_V4.spec
│   ├── app_icon.ico
│   ├── dist/
│   │   └── auto_ccv_V4.exe
│   └── build/            # PyInstaller build artifacts
└── README.md
```

Prebuilt .exe for running program on Windows can be found within **dist** folder of each version.

### Version Details

Each version folder contains:
- `auto_ccv_V*.py` - Main Python application
- `auto_ccv_V*.spec` - PyInstaller specification file
- `app_icon.ico` - Application icon
- `build/` - Build artifacts directory

## V4 - Current Production Version

The **main** branch focuses on V4, the latest and recommended version of the auto CCV control software.

### Features
- Automated CCV rig control and testing
- Data logging and analysis
- Serial communication with hardware
- Configurable test parameters
- GUI-based interface

### Requirements
- Python 3.x
- PySerial
- NumPy (for numerical analysis)
- Pandas (for data manipulation)
- tkinter (usually included with Python)

### Installation

Clone the repository:
```bash
git clone https://github.com/Dan-Cordon/Loop_Auto_CCV.git
cd Loop_Auto_CCV
```

Install dependencies:
```bash
pip install pyserial numpy pandas
```

### Running the Application

Run directly with Python:
```bash
python V4/auto_ccv_V4.py
```

### Building Standalone Executable

To create a standalone Windows executable:
```bash
cd V4
python -m PyInstaller --noconsole --onefile --icon="app_icon.ico" auto_ccv_V4.py
```

The executable will be generated in the `V4/dist/` directory as `auto_ccv_V4.exe`.

## Usage

1. Install Python dependencies
2. Connect the CCV rig hardware via serial port (USB)
3. Run the application
4. Configure test parameters in the GUI
5. Monitor test execution and data output

## Version History

| Version | Status | Notes |
|---------|--------|-------|
| **V4** | In Development | Linear & Power Curve Testing |
| **V3** | Current | Stable Release - Linear Testing Only |
| V2 | Archive |
| V1 | Archive |

## Arduino Firmware

Arduino sketches for different testing modes are stored locally but not included in this repository. Refer to local MCM_CCV_RIG_* folders for firmware files.

## Output

Test results are stored in local `OUTPUT/` directory as CSV files (not tracked in repository).

## Contributing

Please ensure changes are made on appropriate branches before submitting pull requests.

## License

[Add license information]

## Contact & Support

For issues, questions, or contributions, please contact the project maintainer.
