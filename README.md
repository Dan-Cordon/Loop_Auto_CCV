# CCV Rig - Auto Control System

A control and testing system for CCV (Continuously Variable Transmission) rigs. This project includes both Arduino firmware for the rig hardware and Python automation software for testing and analysis.

## Project Structure

- **MCM_CCV_RIG_*** - Arduino sketches for different testing modes:
  - `DutyCycle` - Duty cycle testing
  - `FullRange` - Full range testing
  - `New` - New configuration
  - `PowerCurve` - Power curve analysis
  - `Serial` - Serial communication testing
  - `TEST_ESP` - ESP microcontroller testing

- **V1, V2, V3, V4** - Python application versions with progressively improved functionality
  - Latest: **V4** - Current production version
  - Each includes a PyInstaller build configuration for creating standalone executables

- **OUTPUT** - Test results and data output files (CSV format)

## V4 - Latest Version

The main branch focuses on V4, the latest version of the auto control software.

### Features
- Automated CCV rig control and testing
- Data logging and analysis
- Serial communication with hardware
- Configurable test parameters

### Requirements
- Python 3.x
- PySerial
- NumPy/Pandas (for data analysis)

### Building
To create a standalone executable:
```bash
python -m PyInstaller --noconsole --onefile --icon="app_icon.ico" auto_ccv_V4.py
```

The executable will be generated in the `dist/` directory.

## Getting Started

1. Ensure Python dependencies are installed
2. Connect the CCV rig hardware via serial port
3. Run the application or executable
4. Configure test parameters
5. Monitor output in the `OUTPUT/` directory

## Version History

- **V4** - Current version (main branch)
- **V3** - Previous version
- **V2** - Earlier version
- **V1** - Initial version

## License

[Add appropriate license information]

## Contact

[Add contact information]
