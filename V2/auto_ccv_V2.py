import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import serial
import serial.tools.list_ports
import threading
import time
import csv
import datetime
import os
import json
import ctypes 

class DosingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Dosing Rig Control Panel v2.0")
        self.root.geometry("1100x800") 

        # --- PREVENT WINDOWS SLEEP ---
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000003)
        except:
            pass 

        # Serial Variables
        self.ser = None
        self.is_connected = False
        self.is_running_test = False
        self.stop_test_flag = False

        # Data Variables
        self.current_mass_str = tk.StringVar(value="0.00 g")
        self.current_rate_str = tk.StringVar(value="0.00 g/s")
        self.current_rpm_str = tk.StringVar(value="0 RPM")
        self.test_timer_text = tk.StringVar(value="00:00")
        
        # New CCV Variables
        self.last_ccv_str = tk.StringVar(value="--")
        self.raw_mass_float = 0.0 # Stores raw float for math accuracy

        # Settings Variables
        self.save_filepath = tk.StringVar()
        self.vibration_enabled = tk.BooleanVar(value=True) 

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
        
        ttk.Checkbutton(conn_frame, text="Enable Vibration Motor", variable=self.vibration_enabled, command=self._update_vibration).pack(side="right", padx=20)

        # --- MIDDLE CONTAINER ---
        middle_container = ttk.Frame(self.root)
        middle_container.pack(fill="x", padx=10, pady=5)

        # === LEFT: Live Data Dashboard ===
        dash_frame = ttk.LabelFrame(middle_container, text="Live Readings")
        dash_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))
        
        # Row 0/1: Mass & Rate
        ttk.Label(dash_frame, text="Mass", font=("Arial", 11)).grid(row=0, column=0, padx=10, pady=(10,0))
        ttk.Label(dash_frame, textvariable=self.current_mass_str, font=("Arial", 20, "bold"), foreground="blue").grid(row=1, column=0, padx=10)
        
        ttk.Label(dash_frame, text="Flow Rate", font=("Arial", 11)).grid(row=0, column=1, padx=10, pady=(10,0))
        ttk.Label(dash_frame, textvariable=self.current_rate_str, font=("Arial", 20, "bold"), foreground="green").grid(row=1, column=1, padx=10)

        # Row 0/1: RPM & CCV (New)
        ttk.Label(dash_frame, text="Motor RPM", font=("Arial", 11)).grid(row=0, column=2, padx=10, pady=(10,0))
        ttk.Label(dash_frame, textvariable=self.current_rpm_str, font=("Arial", 20, "bold"), foreground="red").grid(row=1, column=2, padx=10)

        ttk.Label(dash_frame, text="Last Step CCV", font=("Arial", 11)).grid(row=0, column=3, padx=10, pady=(10,0))
        ttk.Label(dash_frame, textvariable=self.last_ccv_str, font=("Arial", 20, "bold"), foreground="purple").grid(row=1, column=3, padx=10)

        self.btn_tare = ttk.Button(dash_frame, text="TARE SCALE", command=self._send_tare, state="disabled")
        self.btn_tare.grid(row=2, column=0, columnspan=4, pady=15, sticky="ew", padx=30)

        # === RIGHT: Manual Control ===
        manual_frame = ttk.LabelFrame(middle_container, text="Manual Control")
        manual_frame.pack(side="right", fill="both", padx=(5, 0), ipadx=10)

        ttk.Label(manual_frame, text="Set Constant Speed:").pack(pady=(15, 5))
        
        input_row = ttk.Frame(manual_frame)
        input_row.pack()
        
        self.entry_manual_rpm = ttk.Entry(input_row, width=8, font=("Arial", 12))
        self.entry_manual_rpm.pack(side="left", padx=5)
        self.entry_manual_rpm.insert(0, "80") 
        ttk.Label(input_row, text="RPM").pack(side="left")

        self.btn_manual_start = ttk.Button(manual_frame, text="Start Manual", command=self._manual_start, state="disabled")
        self.btn_manual_start.pack(fill="x", padx=20, pady=(10, 5))
        
        self.btn_manual_stop = ttk.Button(manual_frame, text="STOP", command=self._manual_stop, state="disabled")
        self.btn_manual_stop.pack(fill="x", padx=20, pady=5)

        # --- 2. Test Builder ---
        builder_frame = ttk.LabelFrame(self.root, text="2. Automated Test Builder")
        builder_frame.pack(fill="both", expand=True, padx=10, pady=10)

        input_frame = ttk.Frame(builder_frame)
        input_frame.pack(fill="x", padx=5, pady=5)
        
        ttk.Label(input_frame, text="RPM:").pack(side="left")
        self.entry_rpm = ttk.Entry(input_frame, width=8)
        self.entry_rpm.pack(side="left", padx=5)
        
        ttk.Label(input_frame, text="Duration (s):").pack(side="left")
        self.entry_time = ttk.Entry(input_frame, width=8)
        self.entry_time.pack(side="left", padx=5)
        
        ttk.Button(input_frame, text="Add Step", command=self._add_step).pack(side="left", padx=10)
        ttk.Button(input_frame, text="Clear", command=self._clear_sequence).pack(side="left")
        
        ttk.Separator(input_frame, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Button(input_frame, text="Save Routine...", command=self._save_routine).pack(side="left", padx=5)
        ttk.Button(input_frame, text="Load Routine...", command=self._load_routine).pack(side="left", padx=5)

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

        # --- Action & Timer ---
        action_frame = ttk.Frame(self.root)
        action_frame.pack(fill="x", padx=10, pady=10)
        
        timer_frame = ttk.Frame(action_frame)
        timer_frame.pack(side="left", padx=20)
        ttk.Label(timer_frame, text="Test Timer:", font=("Arial", 10)).pack(side="left")
        ttk.Label(timer_frame, textvariable=self.test_timer_text, font=("Arial", 14, "bold")).pack(side="left", padx=5)

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
                self._set_ui_connected(True)
                self._update_vibration()
            except Exception as e:
                messagebox.showerror("Error", f"Could not connect: {e}")
        else:
            self._handle_manual_disconnect()

    def _handle_manual_disconnect(self):
        self.is_connected = False
        if self.ser: 
            try: self.ser.close()
            except: pass
        self.ser = None
        self.btn_connect.config(text="Connect")
        self._set_ui_connected(False)

    def _set_ui_connected(self, connected):
        state = "normal" if connected else "disabled"
        self.btn_run.config(state=state)
        self.btn_tare.config(state=state)
        self.btn_manual_start.config(state=state)
        self.btn_manual_stop.config(state=state)
        if not connected:
            self.current_mass_str.set("Disconnected")
            self.current_rate_str.set("--")
            self.current_rpm_str.set("--")

    def _send_tare(self):
        if self.ser and self.is_connected:
            self.ser.write(b"TARE\n")
            self.current_mass_str.set("0.00 g (Taring...)")
            self.current_rate_str.set("0.00 g/s")

    def _update_vibration(self):
        if self.ser and self.is_connected:
            cmd = b"VIB:1\n" if self.vibration_enabled.get() else b"VIB:0\n"
            try: self.ser.write(cmd)
            except: pass 

    def _save_routine(self):
        if not self.sequence_data:
            return
        filepath = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON Files", "*.json")], title="Save Test Routine")
        if filepath:
            try:
                with open(filepath, 'w') as f:
                    json.dump([{"rpm": r, "duration": t} for r, t in self.sequence_data], f, indent=4)
                messagebox.showinfo("Success", f"Saved to {os.path.basename(filepath)}")
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def _load_routine(self):
        filepath = filedialog.askopenfilename(filetypes=[("JSON Files", "*.json")], title="Load Test Routine")
        if filepath:
            try:
                with open(filepath, 'r') as f:
                    loaded_data = json.load(f)
                self._clear_sequence()
                for step in loaded_data:
                    self.sequence_data.append((step["rpm"], step["duration"]))
                    self.tree.insert("", "end", values=(step["rpm"], step["duration"]))
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def _manual_start(self):
        if self.is_running_test:
            messagebox.showwarning("Busy", "Test Running.")
            return
        try:
            rpm = float(self.entry_manual_rpm.get())
            if self.ser and self.is_connected:
                self._update_vibration()
                self.ser.write(f"RPM:{rpm}\n".encode())
        except ValueError:
            messagebox.showwarning("Error", "Invalid RPM.")

    def _manual_stop(self):
        if self.ser and self.is_connected:
            self.ser.write(b"STOP\n")

    def _add_step(self):
        try:
            r = float(self.entry_rpm.get())
            t = float(self.entry_time.get())
            self.sequence_data.append((r, t))
            self.tree.insert("", "end", values=(r, t))
            self.entry_rpm.delete(0, 'end')
            self.entry_time.delete(0, 'end')
        except ValueError:
            messagebox.showwarning("Invalid Input", "Numbers only.")

    def _clear_sequence(self):
        self.sequence_data = []
        for item in self.tree.get_children():
            self.tree.delete(item)
    
    def _browse_file(self):
        default_name = f"Test_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M')}.csv"
        filepath = filedialog.asksaveasfilename(initialfile=default_name, defaultextension=".csv", filetypes=[("CSV Files", "*.csv")], title="Save Results")
        if filepath:
            self.save_filepath.set(filepath)

    def _emergency_stop(self):
        self.stop_test_flag = True
        if self.ser and self.is_connected:
            try: self.ser.write(b"STOP\n")
            except: pass

    def _start_test_thread(self):
        if not self.sequence_data:
            messagebox.showwarning("Empty", "No steps.")
            return
        if not self.save_filepath.get():
            messagebox.showwarning("No File", "Select save location.")
            return
        
        self.stop_test_flag = False
        self.test_timer_text.set("00:00")
        self.last_ccv_str.set("--")
        threading.Thread(target=self._run_test_logic).start()

    def _run_test_logic(self):
        self.is_running_test = True
        self.root.after(0, lambda: self._set_ui_locked_for_test(True))

        filename = self.save_filepath.get()
        summary_filename = filename.replace(".csv", "_Summary.csv")
        
        try:
            self._update_vibration()
            time.sleep(0.1)

            # Open TWO files: one for Raw Data, one for Step Summary
            with open(filename, 'w', newline='') as raw_file, open(summary_filename, 'w', newline='') as sum_file:
                
                raw_writer = csv.writer(raw_file)
                raw_writer.writerow(["Time_s", "TargetRPM", "Mass_g", "Rate_g_s", "Vib_On"])

                sum_writer = csv.writer(sum_file)
                sum_writer.writerow(["Step_Num", "TargetRPM", "Duration_s", "Grams_Dispensed", "CCV_Value"])
                
                start_time = time.time()
                vib_status = "1" if self.vibration_enabled.get() else "0"
                step_count = 0

                for rpm, duration in self.sequence_data:
                    if self.stop_test_flag or not self.is_connected: break
                    step_count += 1
                    
                    # 1. Capture Start Mass
                    start_mass = self.raw_mass_float

                    # 2. Run Step
                    try:
                        self.ser.write(f"RPM:{rpm}\n".encode())
                    except:
                        self.stop_test_flag = True
                        break

                    step_end_time = time.time() + duration
                    
                    while time.time() < step_end_time:
                        if self.stop_test_flag or not self.is_connected: break
                        
                        elapsed = time.time() - start_time
                        
                        # Timer Update
                        elapsed_int = int(elapsed)
                        self.root.after(0, self.test_timer_text.set, f"{elapsed_int // 60:02}:{elapsed_int % 60:02}")

                        # Log Raw Data
                        raw_writer.writerow([round(elapsed, 2), rpm, f"{self.raw_mass_float:.2f}", self.current_rate_str.get().replace(" g/s", ""), vib_status])
                        time.sleep(0.1)

                    # 3. Capture End Mass & Calculate CCV
                    end_mass = self.raw_mass_float
                    mass_delta = end_mass - start_mass
                    
                    # Degrees = (RPM / 60) * 360 * Duration
                    total_degrees = (rpm / 60.0) * 360.0 * duration
                    
                    ccv_val = 0.0
                    if mass_delta > 0.001: # Avoid division by zero
                        ccv_val = (total_degrees / mass_delta) * 100.0
                    
                    # 4. Update UI and Log Summary
                    self.root.after(0, self.last_ccv_str.set, f"{ccv_val:.0f}")
                    sum_writer.writerow([step_count, rpm, duration, f"{mass_delta:.2f}", f"{ccv_val:.1f}"])

                # End of test
                if self.is_connected:
                    try: self.ser.write(b"STOP\n")
                    except: pass
                
            self.root.after(0, lambda: messagebox.showinfo("Done", f"Test Complete.\n\nFiles Saved:\n1. {os.path.basename(filename)}\n2. {os.path.basename(summary_filename)}"))

        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("File Error", f"Write failed:\n{e}"))

        finally:
            self.is_running_test = False
            self.root.after(0, lambda: self._set_ui_locked_for_test(False))

    def _set_ui_locked_for_test(self, locked):
        state = "disabled" if locked else "normal"
        self.btn_run.config(state=state)
        self.btn_browse.config(state=state)
        self.btn_tare.config(state=state)
        self.btn_manual_start.config(state=state)

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
                                    val_str = p.split(':')[1]
                                    try:
                                        self.raw_mass_float = float(val_str) # Store for math
                                        self.root.after(0, self.current_mass_str.set, f"{val_str} g")
                                    except: pass
                                if "Rate" in p:
                                    val = p.split(':')[1]
                                    self.root.after(0, self.current_rate_str.set, f"{val} g/s")
                                if "RPM" in p:
                                    val = p.split(':')[1]
                                    self.root.after(0, self.current_rpm_str.set, f"{val} RPM")
                except serial.SerialException:
                    self.root.after(0, self._handle_manual_disconnect)
                except Exception:
                    pass
            time.sleep(0.01)

if __name__ == "__main__":
    root = tk.Tk()
    app = DosingApp(root)
    root.mainloop()