import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import serial
import serial.tools.list_ports
import threading
import time
import csv
import datetime
import os

class DosingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Dosing Rig Control Panel")
        try:
            self.root.iconbitmap("app_icon.ico")
        except:
            pass # If the icon file is missing, just ignore it and use default
        self.root.geometry("1000x750") # Made wider to fit the side-by-side layout

        # Serial Variables
        self.ser = None
        self.is_connected = False
        self.is_running_test = False
        self.stop_test_flag = False

        # Data Variables
        self.current_mass = tk.StringVar(value="0.00 g")
        self.current_rate = tk.StringVar(value="0.00 g/s")
        self.current_rpm = tk.StringVar(value="0 RPM")
        
        # Settings Variables
        self.save_filepath = tk.StringVar()
        self.vibration_enabled = tk.BooleanVar(value=True) # Default ON

        # Test Sequence List
        self.sequence_data = [] 

        self._setup_ui()
        
        # Start background thread for reading serial
        self.read_thread = threading.Thread(target=self._read_serial_loop, daemon=True)
        self.read_thread.start()

    def _setup_ui(self):
        # --- 1. Connection Frame ---
        conn_frame = ttk.LabelFrame(self.root, text="1. Connection & Settings")
        conn_frame.pack(fill="x", padx=10, pady=5)

        self.port_combo = ttk.Combobox(conn_frame, values=self._get_ports(), width=15)
        self.port_combo.pack(side="left", padx=5, pady=5)
        self.btn_connect = ttk.Button(conn_frame, text="Connect", command=self._toggle_connection)
        self.btn_connect.pack(side="left", padx=5)
        ttk.Button(conn_frame, text="Refresh", command=self._refresh_ports).pack(side="left", padx=5)
        
        # Moved Vibration Checkbox here so it applies to both Manual and Auto modes
        ttk.Checkbutton(conn_frame, text="Enable Vibration Motor", variable=self.vibration_enabled, command=self._update_vibration).pack(side="right", padx=20)


        # --- MIDDLE CONTAINER (Split Left/Right) ---
        middle_container = ttk.Frame(self.root)
        middle_container.pack(fill="x", padx=10, pady=5)

        # === LEFT: Live Data Dashboard ===
        dash_frame = ttk.LabelFrame(middle_container, text="Live Readings")
        dash_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))
        
        # Grid layout for big numbers
        ttk.Label(dash_frame, text="Mass", font=("Arial", 11)).grid(row=0, column=0, padx=10, pady=(10,0))
        ttk.Label(dash_frame, textvariable=self.current_mass, font=("Arial", 20, "bold"), foreground="blue").grid(row=1, column=0, padx=10)
        
        ttk.Label(dash_frame, text="Flow Rate", font=("Arial", 11)).grid(row=0, column=1, padx=10, pady=(10,0))
        ttk.Label(dash_frame, textvariable=self.current_rate, font=("Arial", 20, "bold"), foreground="green").grid(row=1, column=1, padx=10)

        ttk.Label(dash_frame, text="Motor RPM", font=("Arial", 11)).grid(row=0, column=2, padx=10, pady=(10,0))
        ttk.Label(dash_frame, textvariable=self.current_rpm, font=("Arial", 20, "bold"), foreground="red").grid(row=1, column=2, padx=10)

        # TARE BUTTON
        self.btn_tare = ttk.Button(dash_frame, text="TARE SCALE", command=self._send_tare, state="disabled")
        self.btn_tare.grid(row=2, column=0, columnspan=3, pady=15, sticky="ew", padx=30)


        # === RIGHT: Manual Control (New) ===
        manual_frame = ttk.LabelFrame(middle_container, text="Manual Control")
        manual_frame.pack(side="right", fill="both", padx=(5, 0), ipadx=10)

        ttk.Label(manual_frame, text="Set Constant Speed:").pack(pady=(15, 5))
        
        input_row = ttk.Frame(manual_frame)
        input_row.pack()
        
        self.entry_manual_rpm = ttk.Entry(input_row, width=8, font=("Arial", 12))
        self.entry_manual_rpm.pack(side="left", padx=5)
        self.entry_manual_rpm.insert(0, "80") # Default value
        ttk.Label(input_row, text="RPM").pack(side="left")

        # Buttons
        self.btn_manual_start = ttk.Button(manual_frame, text="Start Manual", command=self._manual_start, state="disabled")
        self.btn_manual_start.pack(fill="x", padx=20, pady=(10, 5))
        
        self.btn_manual_stop = ttk.Button(manual_frame, text="STOP", command=self._manual_stop, state="disabled")
        self.btn_manual_stop.pack(fill="x", padx=20, pady=5)


        # --- 2. Test Builder ---
        builder_frame = ttk.LabelFrame(self.root, text="2. Automated Test Builder")
        builder_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Input row
        input_frame = ttk.Frame(builder_frame)
        input_frame.pack(fill="x", padx=5, pady=5)
        
        ttk.Label(input_frame, text="RPM:").pack(side="left")
        self.entry_rpm = ttk.Entry(input_frame, width=10)
        self.entry_rpm.pack(side="left", padx=5)
        
        ttk.Label(input_frame, text="Duration (sec):").pack(side="left")
        self.entry_time = ttk.Entry(input_frame, width=10)
        self.entry_time.pack(side="left", padx=5)
        
        ttk.Button(input_frame, text="Add Step", command=self._add_step).pack(side="left", padx=10)
        ttk.Button(input_frame, text="Clear All", command=self._clear_sequence).pack(side="left")

        # Treeview for sequence
        self.tree = ttk.Treeview(builder_frame, columns=("RPM", "Duration"), show="headings", height=5)
        self.tree.heading("RPM", text="Target RPM")
        self.tree.heading("Duration", text="Duration (s)")
        self.tree.pack(fill="both", expand=True, padx=5, pady=5)

        # --- 3. Output Settings ---
        output_frame = ttk.LabelFrame(self.root, text="3. Output Settings")
        output_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(output_frame, text="Save File Location:").pack(side="left", padx=5)
        self.entry_save = ttk.Entry(output_frame, textvariable=self.save_filepath)
        self.entry_save.pack(side="left", fill="x", expand=True, padx=5)
        self.btn_browse = ttk.Button(output_frame, text="Browse...", command=self._browse_file)
        self.btn_browse.pack(side="left", padx=5)

        # --- Action Buttons ---
        action_frame = ttk.Frame(self.root)
        action_frame.pack(fill="x", padx=10, pady=10)
        
        self.btn_run = ttk.Button(action_frame, text="RUN TEST SEQUENCE", command=self._start_test_thread, state="disabled")
        self.btn_run.pack(side="right", padx=10)
        
        ttk.Button(action_frame, text="EMERGENCY STOP", command=self._emergency_stop).pack(side="right", padx=10)

    # --- Logic ---
    def _get_ports(self):
        return [port.device for port in serial.tools.list_ports.comports()]

    def _refresh_ports(self):
        self.port_combo['values'] = self._get_ports()

    def _toggle_connection(self):
        if not self.is_connected:
            try:
                port = self.port_combo.get()
                self.ser = serial.Serial(port, 115200, timeout=1)
                self.is_connected = True
                self.btn_connect.config(text="Disconnect")
                
                # Enable Buttons
                self.btn_run.config(state="normal")
                self.btn_tare.config(state="normal")
                self.btn_manual_start.config(state="normal")
                self.btn_manual_stop.config(state="normal")
                
                # Send initial vibration state
                self._update_vibration()
                
            except Exception as e:
                messagebox.showerror("Error", f"Could not connect: {e}")
        else:
            self.is_connected = False
            if self.ser: self.ser.close()
            self.btn_connect.config(text="Connect")
            
            # Disable Buttons
            self.btn_run.config(state="disabled")
            self.btn_tare.config(state="disabled")
            self.btn_manual_start.config(state="disabled")
            self.btn_manual_stop.config(state="disabled")

    def _send_tare(self):
        if self.ser and self.is_connected:
            self.ser.write(b"TARE\n")
            self.current_mass.set("0.00 g (Taring...)")
            self.current_rate.set("0.00 g/s")

    def _update_vibration(self):
        if self.ser and self.is_connected:
            if self.vibration_enabled.get():
                self.ser.write(b"VIB:1\n")
            else:
                self.ser.write(b"VIB:0\n")

    # --- MANUAL CONTROL LOGIC ---
    def _manual_start(self):
        # Prevent Manual Start if a Test Sequence is running
        if self.is_running_test:
            messagebox.showwarning("Busy", "Cannot use Manual Control while Test Sequence is running.")
            return

        try:
            rpm = float(self.entry_manual_rpm.get())
            if self.ser and self.is_connected:
                self._update_vibration() # Ensure vib setting is current
                cmd = f"RPM:{rpm}\n"
                self.ser.write(cmd.encode())
        except ValueError:
            messagebox.showwarning("Error", "Invalid RPM value.")

    def _manual_stop(self):
        if self.ser and self.is_connected:
            self.ser.write(b"STOP\n")

    # --- TEST BUILDER LOGIC ---
    def _add_step(self):
        try:
            r = float(self.entry_rpm.get())
            t = float(self.entry_time.get())
            self.sequence_data.append((r, t))
            self.tree.insert("", "end", values=(r, t))
            self.entry_rpm.delete(0, 'end')
            self.entry_time.delete(0, 'end')
        except ValueError:
            messagebox.showwarning("Invalid Input", "Please enter numeric values.")

    def _clear_sequence(self):
        self.sequence_data = []
        for item in self.tree.get_children():
            self.tree.delete(item)
    
    def _browse_file(self):
        default_name = f"Test_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M')}.csv"
        filepath = filedialog.asksaveasfilename(
            initialfile=default_name,
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
            title="Save Test Results As..."
        )
        if filepath:
            self.save_filepath.set(filepath)

    def _emergency_stop(self):
        self.stop_test_flag = True
        if self.ser and self.is_connected:
            self.ser.write(b"STOP\n")

    def _start_test_thread(self):
        if not self.sequence_data:
            messagebox.showwarning("Empty", "No steps in sequence.")
            return
        
        if not self.save_filepath.get():
            messagebox.showwarning("No File", "Please select a save location/filename first.")
            return
        
        self.stop_test_flag = False
        threading.Thread(target=self._run_test_logic).start()

    def _run_test_logic(self):
        self.is_running_test = True
        
        # Lock UI during test
        self.root.after(0, lambda: self._set_ui_state("disabled"))

        filename = self.save_filepath.get()
        
        try:
            # Force vibration setting before start
            self._update_vibration()
            time.sleep(0.1)

            with open(filename, 'w', newline='') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["Time_s", "TargetRPM", "ActualMass_g", "ActualRate_g_s", "Vibration_On"])
                
                start_time = time.time()
                vib_status = "1" if self.vibration_enabled.get() else "0"

                for rpm, duration in self.sequence_data:
                    if self.stop_test_flag: break
                    
                    # Send Command
                    cmd = f"RPM:{rpm}\n"
                    self.ser.write(cmd.encode())
                    
                    # Wait for duration
                    step_end = time.time() + duration
                    while time.time() < step_end:
                        if self.stop_test_flag: break
                        
                        elapsed = time.time() - start_time
                        m_val = self.current_mass.get().replace(" g", "")
                        r_val = self.current_rate.get().replace(" g/s", "")
                        
                        writer.writerow([round(elapsed, 2), rpm, m_val, r_val, vib_status])
                        time.sleep(0.1)

                # End of test
                self.ser.write(b"STOP\n")
                
            self.root.after(0, lambda: messagebox.showinfo("Done", f"Test Complete.\nSaved to:\n{filename}"))

        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("File Error", f"Could not write to file:\n{e}"))

        finally:
            self.is_running_test = False
            self.root.after(0, lambda: self._set_ui_state("normal"))

    def _set_ui_state(self, state):
        self.btn_run.config(state=state)
        self.btn_browse.config(state=state)
        self.btn_tare.config(state=state)
        self.btn_manual_start.config(state=state)
        # Note: We do NOT disable Emergency Stop or Manual Stop usually, 
        # but for safety in automated test, we might want manual stop to just kill the test.
        # Here we just re-enable them after test.

    def _read_serial_loop(self):
        while True:
            if self.is_connected and self.ser:
                try:
                    if self.ser.in_waiting:
                        line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                        if "Mass:" in line:
                            parts = line.split(',')
                            for p in parts:
                                if "Mass" in p:
                                    val = p.split(':')[1]
                                    self.root.after(0, self.current_mass.set, f"{val} g")
                                if "Rate" in p:
                                    val = p.split(':')[1]
                                    self.root.after(0, self.current_rate.set, f"{val} g/s")
                                if "RPM" in p:
                                    val = p.split(':')[1]
                                    self.root.after(0, self.current_rpm.set, f"{val} RPM")
                except Exception:
                    pass
            time.sleep(0.01)

if __name__ == "__main__":
    root = tk.Tk()
    app = DosingApp(root)
    root.mainloop()