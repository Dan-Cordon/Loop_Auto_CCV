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
import math
from collections import deque 

# --- GRAPHING IMPORTS ---
import matplotlib
matplotlib.use("TkAgg") 
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib import style

class DosingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Dosing Rig Control Panel")
        self.root.geometry("1280x980") 

        # Prevent Windows Sleep
        try: ctypes.windll.kernel32.SetThreadExecutionState(0x80000003)
        except: pass 

        # Serial & State
        self.ser = None
        self.is_connected = False
        self.is_running_test = False
        self.is_manual_active = False 
        self.stop_test_flag = False

        # Live Data
        self.current_mass_str = tk.StringVar(value="0.00 g")
        self.current_rate_str = tk.StringVar(value="0.00 g/s")
        self.current_rpm_str = tk.StringVar(value="0 RPM")
        self.test_timer_text = tk.StringVar(value="00:00")
        self.last_ccv_str = tk.StringVar(value="--") # Restored from V3
        
        self.raw_mass_float = 0.0 
        self.raw_rate_float = 0.0
        self.live_rpm_float = 0.0

        # Graph Data (Preserving 10s Average)
        self.graph_time = []
        self.graph_mass = []
        self.graph_rate_raw = []
        self.graph_rate_avg = [] 
        self.rate_window = deque(maxlen=100) # 100 * 0.1s = 10s window
        self.start_time_offset = 0.0

        # Settings
        self.save_filepath = tk.StringVar()
        self.vibration_enabled = tk.BooleanVar(value=True) 
        self.manual_mode_var = tk.StringVar(value="RPM")
        self.builder_mode_var = tk.StringVar(value="RPM")
        
        # NEW: Operation Mode Switch
        self.operation_mode = tk.StringVar(value="CCV") # "CCV" or "CAL"

        # Test Data Containers
        self.sequence_data = [] 
        self.last_calibration_results = [] 

        self._setup_ui()
        
        # Threads
        threading.Thread(target=self._read_serial_loop, daemon=True).start()
        self._animate_graph()

    def _setup_ui(self):
        # --- 1. Connection & Global Settings ---
        conn_frame = ttk.LabelFrame(self.root, text="1. Connection & Settings")
        conn_frame.pack(fill="x", padx=10, pady=5)

        self.port_combo = ttk.Combobox(conn_frame, values=self._get_ports(), width=15)
        self.port_combo.pack(side="left", padx=5, pady=5)
        self.btn_connect = ttk.Button(conn_frame, text="Connect", command=self._toggle_connection)
        self.btn_connect.pack(side="left", padx=5)
        ttk.Button(conn_frame, text="Refresh", command=self._refresh_ports).pack(side="left", padx=5)
        
        ttk.Checkbutton(conn_frame, text="Enable Vibration", variable=self.vibration_enabled, command=self._update_vibration).pack(side="right", padx=20)

        # --- MIDDLE CONTAINER ---
        middle_container = ttk.Frame(self.root)
        middle_container.pack(fill="x", padx=10, pady=5)

        # === LEFT: Live Data Dashboard ===
        dash_frame = ttk.LabelFrame(middle_container, text="Live Readings")
        dash_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))
        
        # Grid Layout
        ttk.Label(dash_frame, text="Mass", font=("Arial", 11)).grid(row=0, column=0, padx=10, pady=(10,0))
        ttk.Label(dash_frame, textvariable=self.current_mass_str, font=("Arial", 20, "bold"), foreground="blue").grid(row=1, column=0, padx=10)
        
        ttk.Label(dash_frame, text="Flow Rate", font=("Arial", 11)).grid(row=0, column=1, padx=10, pady=(10,0))
        ttk.Label(dash_frame, textvariable=self.current_rate_str, font=("Arial", 20, "bold"), foreground="green").grid(row=1, column=1, padx=10)

        ttk.Label(dash_frame, text="Motor RPM", font=("Arial", 11)).grid(row=0, column=2, padx=10, pady=(10,0))
        ttk.Label(dash_frame, textvariable=self.current_rpm_str, font=("Arial", 20, "bold"), foreground="red").grid(row=1, column=2, padx=10)

        # Restored CCV Display
        ttk.Label(dash_frame, text="Last Step CCV", font=("Arial", 11)).grid(row=0, column=3, padx=10, pady=(10,0))
        ttk.Label(dash_frame, textvariable=self.last_ccv_str, font=("Arial", 20, "bold"), foreground="purple").grid(row=1, column=3, padx=10)

        self.btn_tare = ttk.Button(dash_frame, text="TARE SCALE", command=self._send_tare, state="disabled")
        self.btn_tare.grid(row=2, column=0, columnspan=4, pady=15, sticky="ew", padx=30)

        # === RIGHT: Manual Control ===
        manual_frame = ttk.LabelFrame(middle_container, text="Manual Control")
        manual_frame.pack(side="right", fill="both", padx=(5, 0), ipadx=10)

        mode_frame = ttk.Frame(manual_frame)
        mode_frame.pack(pady=(10, 5))
        ttk.Radiobutton(mode_frame, text="RPM", variable=self.manual_mode_var, value="RPM").pack(side="left", padx=5)
        ttk.Radiobutton(mode_frame, text="Rate (g/s)", variable=self.manual_mode_var, value="RATE").pack(side="left", padx=5)

        input_row = ttk.Frame(manual_frame)
        input_row.pack(pady=5)
        self.entry_manual_val = ttk.Entry(input_row, width=8, font=("Arial", 12))
        self.entry_manual_val.pack(side="left", padx=5)
        self.entry_manual_val.insert(0, "80") 

        self.btn_manual_start = ttk.Button(manual_frame, text="Start", command=self._manual_start, state="disabled")
        self.btn_manual_start.pack(fill="x", padx=20, pady=(10, 5))
        self.btn_manual_stop = ttk.Button(manual_frame, text="STOP", command=self._manual_stop, state="disabled")
        self.btn_manual_stop.pack(fill="x", padx=20, pady=5)

        # --- GRAPH FRAME ---
        graph_frame = ttk.LabelFrame(self.root, text="Live Data Plot")
        graph_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        style.use('ggplot')
        self.fig = Figure(figsize=(5, 3), dpi=100)
        self.ax1 = self.fig.add_subplot(111)
        self.ax2 = self.ax1.twinx()
        
        self.line_mass, = self.ax1.plot([], [], 'b-', label='Mass (g)', linewidth=1.5)
        self.line_rate_raw, = self.ax2.plot([], [], color='limegreen', alpha=0.3, linewidth=1, label='Raw Rate')
        self.line_rate_avg, = self.ax2.plot([], [], color='darkgreen', linewidth=2.5, label='10s Avg Rate')
        
        self.ax1.set_ylabel('Mass (g)', color='b')
        self.ax2.set_ylabel('Flow Rate (g/s)', color='darkgreen')
        
        lines = [self.line_mass, self.line_rate_raw, self.line_rate_avg]
        labels = [l.get_label() for l in lines]
        self.ax1.legend(lines, labels, loc='upper left')

        self.canvas = FigureCanvasTkAgg(self.fig, master=graph_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(side="left", fill="both", expand=True)

        ttk.Button(graph_frame, text="Clear Graph", command=self._reset_graph_data).pack(side="right", padx=10)

        # --- 2. Test Builder ---
        builder_frame = ttk.LabelFrame(self.root, text="2. Automated Test / Calibration Builder")
        builder_frame.pack(fill="x", padx=10, pady=5)

        # MODE SELECTION (The Core of V6)
        mode_select_frame = ttk.Frame(builder_frame)
        mode_select_frame.pack(fill="x", pady=5, padx=5)
        ttk.Label(mode_select_frame, text="Test Operation Mode:", font=("Arial", 10, "bold")).pack(side="left")
        
        r1 = ttk.Radiobutton(mode_select_frame, text="Standard CCV (V3 Style - RPM Only, Summary Report)", variable=self.operation_mode, value="CCV")
        r1.pack(side="left", padx=15)
        r2 = ttk.Radiobutton(mode_select_frame, text="Flow Calibration (New - Curve Fitting)", variable=self.operation_mode, value="CAL")
        r2.pack(side="left", padx=15)

        # Input Frame
        input_frame = ttk.Frame(builder_frame)
        input_frame.pack(fill="x", padx=5, pady=5)
        
        ttk.Label(input_frame, text="Step Type:").pack(side="left")
        self.combo_builder_mode = ttk.Combobox(input_frame, textvariable=self.builder_mode_var, values=["RPM", "RATE"], width=6, state="readonly")
        self.combo_builder_mode.pack(side="left", padx=5)
        
        ttk.Label(input_frame, text="Value:").pack(side="left")
        self.entry_builder_val = ttk.Entry(input_frame, width=8)
        self.entry_builder_val.pack(side="left", padx=5)
        
        ttk.Label(input_frame, text="Duration (s):").pack(side="left")
        self.entry_builder_time = ttk.Entry(input_frame, width=8)
        self.entry_builder_time.pack(side="left", padx=5)
        
        ttk.Button(input_frame, text="Add Step", command=self._add_step).pack(side="left", padx=10)
        ttk.Button(input_frame, text="Clear List", command=self._clear_sequence).pack(side="left")
        ttk.Separator(input_frame, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Button(input_frame, text="Save Routine...", command=self._save_routine).pack(side="left", padx=5)
        ttk.Button(input_frame, text="Load Routine...", command=self._load_routine).pack(side="left", padx=5)

        self.tree = ttk.Treeview(builder_frame, columns=("Mode", "Value", "Duration"), show="headings", height=4)
        self.tree.heading("Mode", text="Type")
        self.tree.heading("Value", text="Target")
        self.tree.heading("Duration", text="Duration (s)")
        self.tree.pack(fill="both", expand=True, padx=5, pady=5)

        # --- 3. Execution ---
        action_frame = ttk.Frame(self.root)
        action_frame.pack(fill="x", padx=10, pady=10)
        
        ttk.Label(action_frame, text="Save To:").pack(side="left")
        self.entry_save = ttk.Entry(action_frame, textvariable=self.save_filepath, width=40)
        self.entry_save.pack(side="left", padx=5)
        ttk.Button(action_frame, text="Browse", command=self._browse_file).pack(side="left", padx=5)

        self.btn_run = ttk.Button(action_frame, text="RUN TEST SEQUENCE", command=self._start_test_thread, state="disabled")
        self.btn_run.pack(side="right", padx=10)
        
        ttk.Button(action_frame, text="EMERGENCY STOP", command=self._emergency_stop).pack(side="right", padx=10)

    # --- LOGIC: Test Runner ---
    def _start_test_thread(self):
        if not self.sequence_data:
            messagebox.showwarning("Empty", "No steps in sequence.")
            return
        if not self.save_filepath.get():
            messagebox.showwarning("No File", "Select save location first.")
            return
        
        self.stop_test_flag = False
        self.test_timer_text.set("00:00")
        self.last_ccv_str.set("--")
        self._reset_graph_data()
        threading.Thread(target=self._run_test_logic, daemon=True).start()

    def _run_test_logic(self):
        self.is_running_test = True
        self.last_calibration_results = []
        op_mode = self.operation_mode.get() # Check mode: "CCV" or "CAL"
        
        self.root.after(0, lambda: self._set_ui_locked_for_test(True))
        filename = self.save_filepath.get()
        summary_filename = filename.replace(".csv", "_Summary.csv")
        
        try:
            self._update_vibration()
            time.sleep(0.1)

            # Open Files: 
            # 1. Raw File (Always used)
            # 2. Summary File (Only used if in CCV mode)
            
            raw_file = open(filename, 'w', newline='') 
            raw_writer = csv.writer(raw_file)
            # Generic Header
            raw_writer.writerow(["Time_s", "Mode", "Value", "Mass_g", "Rate_g_s", "Vib_On"])
            
            sum_file = None
            sum_writer = None
            
            if op_mode == "CCV":
                sum_file = open(summary_filename, 'w', newline='')
                sum_writer = csv.writer(sum_file)
                # V3 Standard Header
                sum_writer.writerow(["Step_Num", "TargetRPM", "Duration_s", "Grams_Dispensed", "CCV_Value"])

            start_time = time.time()
            step_count = 0
            vib_status = "1" if self.vibration_enabled.get() else "0"

            for step in self.sequence_data:
                if self.stop_test_flag or not self.is_connected: break
                step_count += 1
                
                mode = step["type"]
                val = step["val"]
                duration = step["duration"]
                
                # --- V3 CCV ENFORCEMENT ---
                if op_mode == "CCV" and mode == "RATE":
                    # Warning: CCV mode logic relies on RPM. 
                    # We will run it, but CCV math will be meaningless if we don't know RPM.
                    pass 

                # Send Command
                cmd_str = f"RPM:{val}\n" if mode == "RPM" else f"RATE:{val}\n"
                self.ser.write(cmd_str.encode())

                step_start_mass = self.raw_mass_float
                step_end = time.time() + duration
                rate_accumulator = [] 
                
                while time.time() < step_end:
                    if self.stop_test_flag: break
                    elapsed = time.time() - start_time
                    
                    # Calibration Data Collection (Skip start transient)
                    if (time.time() - (step_end - duration)) > 2.0:
                            rate_accumulator.append(self.raw_rate_float)

                    # Log Raw
                    raw_writer.writerow([round(elapsed, 2), mode, val, f"{self.raw_mass_float:.2f}", f"{self.raw_rate_float:.2f}", vib_status])
                    raw_file.flush()
                    time.sleep(0.1)

                # --- END OF STEP LOGIC ---
                
                # 1. Calibration Data Store
                if mode == "RPM":
                    avg_rate = sum(rate_accumulator)/len(rate_accumulator) if rate_accumulator else 0
                    self.last_calibration_results.append((val, avg_rate))

                # 2. CCV Summary Logic (V3 Feature)
                if op_mode == "CCV":
                    step_end_mass = self.raw_mass_float
                    mass_delta = step_end_mass - step_start_mass
                    
                    # Calculate CCV
                    # Formula: CCV = (Degrees Rotated / Grams Dispensed) * 100
                    # Note: Only valid if Mode was RPM.
                    ccv_val = 0.0
                    if mode == "RPM":
                        total_degrees = (val / 60.0) * 360.0 * duration
                        if mass_delta > 0.001:
                            ccv_val = (total_degrees / mass_delta) * 100.0
                    
                    self.root.after(0, self.last_ccv_str.set, f"{ccv_val:.0f}")
                    if sum_writer:
                        sum_writer.writerow([step_count, val, duration, f"{mass_delta:.2f}", f"{ccv_val:.1f}"])
                        sum_file.flush()

            # End Loop
            if self.is_connected: self.ser.write(b"STOP\n")
            
            # Clean up files
            raw_file.close()
            if sum_file: sum_file.close()
            
            # Final Popups
            if op_mode == "CAL" and len(self.last_calibration_results) > 0:
                self.root.after(0, self._perform_regression)
            else:
                self.root.after(0, lambda: messagebox.showinfo("Done", "Test Complete."))

        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", str(e)))

        finally:
            self.is_running_test = False
            self.root.after(0, lambda: self._set_ui_locked_for_test(False))

    # --- MATH & CALIBRATION (New V4/V5 Feature) ---
    def _perform_regression(self):
        valid_points = []
        for rpm, rate in self.last_calibration_results:
            if rpm > 0 and rate > 0.01:
                valid_points.append((rpm, rate))
        
        if len(valid_points) < 2:
            messagebox.showwarning("Calibration Failed", "Not enough valid data points.")
            return

        sum_ln_x = 0; sum_ln_y = 0; sum_ln_x_ln_y = 0; sum_sq_ln_x = 0; n = len(valid_points)

        for rpm, rate in valid_points:
            ln_x = math.log(rate)
            ln_y = math.log(rpm)
            sum_ln_x += ln_x; sum_ln_y += ln_y
            sum_ln_x_ln_y += (ln_x * ln_y); sum_sq_ln_x += (ln_x * ln_x)

        try:
            b_val = (n * sum_ln_x_ln_y - sum_ln_x * sum_ln_y) / (n * sum_sq_ln_x - sum_ln_x**2)
            ln_a = (sum_ln_y - b_val * sum_ln_x) / n
            a_val = math.exp(ln_a)
        except:
            messagebox.showerror("Error", "Math Error in Regression.")
            return

        msg = f"New Curve Calculated!\n\nRPM = {a_val:.2f} * Rate^{b_val:.2f}\n\nUpload to Rig?"
        if messagebox.askyesno("Calibration", msg):
            self._upload_calibration(a_val, b_val)

    def _upload_calibration(self, a, b):
        if self.ser and self.is_connected:
            cmd = f"CAL:{a:.3f},{b:.3f}\n"
            self.ser.write(cmd.encode())
            messagebox.showinfo("Success", "Calibration saved to Rig.")

    # --- UI & UTILS ---
    def _get_ports(self): return [port.device for port in serial.tools.list_ports.comports()]
    def _refresh_ports(self): self.port_combo['values'] = self._get_ports()
    
    def _toggle_connection(self):
        if not self.is_connected:
            try:
                self.ser = serial.Serial(self.port_combo.get(), 115200, timeout=1)
                self.is_connected = True
                self.btn_connect.config(text="Disconnect")
                self._set_ui_connected(True)
            except: messagebox.showerror("Error", "Connect Failed")
        else:
            self._handle_manual_disconnect()

    def _handle_manual_disconnect(self):
        self.is_connected = False
        if self.ser: self.ser.close()
        self.btn_connect.config(text="Connect")
        self._set_ui_connected(False)

    def _set_ui_connected(self, connected):
        s = "normal" if connected else "disabled"
        self.btn_run.config(state=s)
        self.btn_tare.config(state=s)
        self.btn_manual_start.config(state=s)
        self.btn_manual_stop.config(state=s)

    def _send_tare(self): 
        if self.ser: self.ser.write(b"TARE\n")
        self._reset_graph_data()

    def _reset_graph_data(self):
        self.graph_time = []
        self.graph_mass = []
        self.graph_rate_raw = []
        self.graph_rate_avg = []
        self.rate_window.clear()
        self.start_time_offset = time.time()
        self.canvas.draw()

    def _update_vibration(self):
        if self.ser: self.ser.write(b"VIB:1\n" if self.vibration_enabled.get() else b"VIB:0\n")

    def _manual_start(self):
        try:
            val = float(self.entry_manual_val.get())
            cmd = f"RPM:{val}\n" if self.manual_mode_var.get() == "RPM" else f"RATE:{val}\n"
            if self.ser: self.ser.write(cmd.encode())
            self.is_manual_active = True
            if not self.graph_time: self.start_time_offset = time.time()
        except: pass

    def _manual_stop(self):
        if self.ser: self.ser.write(b"STOP\n")
        self.is_manual_active = False

    def _add_step(self):
        try:
            m = self.builder_mode_var.get()
            v = float(self.entry_builder_val.get())
            d = float(self.entry_builder_time.get())
            self.sequence_data.append({"type": m, "val": v, "duration": d})
            self.tree.insert("", "end", values=(m, v, d))
        except: pass
    
    def _save_routine(self):
        if not self.sequence_data: return
        f = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if f:
            with open(f, 'w') as file: json.dump(self.sequence_data, file, indent=4)
            
    def _load_routine(self):
        f = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if f:
            with open(f, 'r') as file:
                data = json.load(file)
                self._clear_sequence()
                # Support V3 (rpm, duration) and V4+ (type, val, duration)
                for step in data:
                    if isinstance(step, dict):
                        # V4/V5/V6 format
                        m = step.get("type", "RPM")
                        v = step.get("val", 0)
                        d = step.get("duration", 0)
                        self.sequence_data.append({"type": m, "val": v, "duration": d})
                        self.tree.insert("", "end", values=(m, v, d))
                    elif isinstance(step, list):
                        # V3 format (simple list of [rpm, duration])
                        # We assume these are RPM
                        self.sequence_data.append({"type": "RPM", "val": step[0], "duration": step[1]})
                        self.tree.insert("", "end", values=("RPM", step[0], step[1]))


    def _clear_sequence(self):
        self.sequence_data = []
        for i in self.tree.get_children(): self.tree.delete(i)

    def _browse_file(self):
        fname = f"Test_{datetime.datetime.now().strftime('%H-%M')}.csv"
        f = filedialog.asksaveasfilename(initialfile=fname, defaultextension=".csv")
        if f: self.save_filepath.set(f)

    def _emergency_stop(self):
        self.stop_test_flag = True
        if self.ser: self.ser.write(b"STOP\n")

    def _set_ui_locked_for_test(self, locked):
        s = "disabled" if locked else "normal"
        self.btn_run.config(state=s)

    def _read_serial_loop(self):
        while True:
            if self.is_connected and self.ser:
                try:
                    if self.ser.in_waiting:
                        line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                        if "Mass:" in line:
                            parts = line.split(',')
                            for p in parts:
                                if "Mass" in p: self.raw_mass_float = float(p.split(':')[1])
                                if "Rate" in p: self.raw_rate_float = float(p.split(':')[1])
                                if "RPM" in p: 
                                    try: self.live_rpm_float = float(p.split(':')[1])
                                    except: pass
                                    self.root.after(0, self.current_rpm_str.set, f"{int(self.live_rpm_float)} RPM")
                            
                            self.root.after(0, self.current_mass_str.set, f"{self.raw_mass_float:.2f} g")
                            self.root.after(0, self.current_rate_str.set, f"{self.raw_rate_float:.2f} g/s")
                            
                            if self.is_running_test or self.is_manual_active:
                                self.rate_window.append(self.raw_rate_float)
                                avg = sum(self.rate_window)/len(self.rate_window)
                                t = len(self.graph_time) * 0.1 if self.is_running_test else time.time() - self.start_time_offset
                                self.graph_time.append(t)
                                self.graph_mass.append(self.raw_mass_float)
                                self.graph_rate_raw.append(self.raw_rate_float)
                                self.graph_rate_avg.append(avg)
                except: pass
            time.sleep(0.01)

    def _animate_graph(self):
        if len(self.graph_time) > 1:
            self.line_mass.set_data(self.graph_time, self.graph_mass)
            self.line_rate_raw.set_data(self.graph_time, self.graph_rate_raw)
            self.line_rate_avg.set_data(self.graph_time, self.graph_rate_avg)
            self.ax1.relim(); self.ax1.autoscale_view()
            self.ax2.relim(); self.ax2.autoscale_view()
            self.canvas.draw()
        self.root.after(500, self._animate_graph)

if __name__ == "__main__":
    root = tk.Tk()
    app = DosingApp(root)
    root.mainloop()