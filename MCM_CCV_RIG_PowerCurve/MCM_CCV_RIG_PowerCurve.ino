#include <driver/rmt.h>
#include "driver/gpio.h"
#include "driver/timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include <math.h> 
#include "HX711.h"
#include <Preferences.h> // NEW: For saving calibration to flash

// --- Configuration Constants ---
#define LOADCELL_DOUT_PIN 40
#define LOADCELL_SCK_PIN  42
#define BUTTON_PIN        GPIO_NUM_39   
#define TRIG_PIN          GPIO_NUM_41   
#define VIBRATION_PIN     GPIO_NUM_48   

// --- Motor 5 Configuration ---
#define MOTOR_INDEX       5 
const gpio_num_t STEP_PIN = GPIO_NUM_15;
const gpio_num_t DIR_PIN  = GPIO_NUM_16; 
const gpio_num_t EN_PIN   = GPIO_NUM_17;

// --- Low Speed Duty Cycle Settings ---
#define MIN_STABLE_RPM       10.0f   
#define DUTY_CYCLE_PERIOD_MS 1000    
#define STARTUP_LATENCY_MS   20      

// --- Acceleration Settings ---
float currentPhysicalRPM = 0.0f;     
const float ACCEL_STEP = 2.0f;       

// Duty Cycle State Tracking
unsigned long lastCycleStart = 0;
bool isDutyCycleActive = false;

#define MICROSTEPS 400
#define MOTOR_RPM  80.0f  

// --- Flow Calibration Variables ---
// Defaults (Linear-ish)
float FLOW_CURVE_A = 15.0f; 
float FLOW_CURVE_B = 1.0f;  

// Load Cell Settings
#define RATE_SAMPLE_INTERVAL_MS 100
#define RATE_WINDOW_SECONDS     1
#define HISTORY_SIZE            (RATE_WINDOW_SECONDS * 1000 / RATE_SAMPLE_INTERVAL_MS)
#define SMOOTHING_ALPHA 0.3 

// --- Global Variables ---
HX711 scale;
Preferences preferences; // NEW: Storage object
float massHistory[HISTORY_SIZE];
int historyIndex = 0;
bool bufferFull = false;
float calibration_factor = 45.31945101751073f;

// --- VOLATILE VARIABLES ---
volatile bool motorRunning = false;
volatile bool motorStepLevel = false;
volatile float currentMass = 0.0f;
volatile float currentRate = 0.0f;
volatile bool tareRequested = false;

// Control Globals
float targetRPM = 0.0f;
bool serialControlActive = false;
bool vibrationEnabled = true;
unsigned long lastSerialPrint = 0;

// --- Timer Interrupt ---
bool IRAM_ATTR onTimer(void *arg) {
    if (!motorRunning) return false;
    motorStepLevel = !motorStepLevel;
    gpio_set_level(STEP_PIN, motorStepLevel);
    return true;
}

void setupMotorTimer() {
    timer_config_t config = {
        .alarm_en    = TIMER_ALARM_EN,
        .counter_en  = TIMER_PAUSE,
        .intr_type   = TIMER_INTR_LEVEL,
        .counter_dir = TIMER_COUNT_UP,
        .auto_reload = TIMER_AUTORELOAD_EN,
        .divider     = 80 
    };
    timer_init(TIMER_GROUP_0, TIMER_0, &config);
    timer_set_counter_value(TIMER_GROUP_0, TIMER_0, 0);
    timer_isr_callback_add(TIMER_GROUP_0, TIMER_0, onTimer, NULL, 0);
}

void setMotorSpeed(float rpm) {
    if (rpm <= 0) {
        timer_pause(TIMER_GROUP_0, TIMER_0);
        motorRunning = false;
        gpio_set_level(STEP_PIN, 0);
        return;
    }
    float freqHz = rpm * MICROSTEPS / 60.0f;
    int period_us = (int)(1e6f / (freqHz * 2));
    if (period_us < 1) period_us = 1;
    timer_set_alarm_value(TIMER_GROUP_0, TIMER_0, period_us);
    
    if (!motorRunning) {
        timer_start(TIMER_GROUP_0, TIMER_0);
        motorRunning = true;
    }
}

// --- Load Cell Task ---
void loadCellTask(void *pvParameters) {
    scale.begin(LOADCELL_DOUT_PIN, LOADCELL_SCK_PIN);
    scale.set_scale(calibration_factor);
    scale.tare();
    for (int i = 0; i < HISTORY_SIZE; i++) massHistory[i] = 0.0f;
    float filteredReading = 0.0f;
    TickType_t xLastWakeTime = xTaskGetTickCount();
    const TickType_t xFrequency = pdMS_TO_TICKS(RATE_SAMPLE_INTERVAL_MS);

    while (true) {
        if (tareRequested) {
            scale.tare();
            filteredReading = 0.0f;
            currentMass = 0.0f;
            currentRate = 0.0f;
            for (int i = 0; i < HISTORY_SIZE; i++) massHistory[i] = 0.0f;
            tareRequested = false; 
        }
        if (scale.is_ready()) {
            float rawReading = scale.get_units(1);
            filteredReading = (SMOOTHING_ALPHA * rawReading) + ((1.0 - SMOOTHING_ALPHA) * filteredReading);
            currentMass = filteredReading;
            float oldMass = massHistory[historyIndex];
            massHistory[historyIndex] = filteredReading;
            historyIndex = (historyIndex + 1) % HISTORY_SIZE;
            if (historyIndex == 0) bufferFull = true;
            if (bufferFull) {
                currentRate = (filteredReading - oldMass) / (float)RATE_WINDOW_SECONDS;
            }
        }
        vTaskDelayUntil(&xLastWakeTime, xFrequency);
    }
}

float calculateRPM(float desiredRate) {
    if (desiredRate <= 0) return 0.0f;
    // Uses the A and B values stored in memory
    float requiredRPM = FLOW_CURVE_A * pow(desiredRate, FLOW_CURVE_B);
    if (requiredRPM > 300.0f) requiredRPM = 300.0f; 
    return requiredRPM;
}

void manageMotorControl(float target, bool vibration) {
    if (target <= 0) {
        setMotorSpeed(0);
        if (vibration) gpio_set_level(VIBRATION_PIN, 0);
        currentPhysicalRPM = 0.0f;
        isDutyCycleActive = false;
        return;
    }
    float effectiveRPM = target;
    if (target >= MIN_STABLE_RPM) {
        if (currentPhysicalRPM < target) {
            currentPhysicalRPM += ACCEL_STEP;
            if (currentPhysicalRPM > target) currentPhysicalRPM = target;
        } 
        else if (currentPhysicalRPM > target) {
            currentPhysicalRPM -= ACCEL_STEP;
            if (currentPhysicalRPM < target) currentPhysicalRPM = target;
        }
        effectiveRPM = currentPhysicalRPM;
    }
    if (effectiveRPM >= MIN_STABLE_RPM) {
        setMotorSpeed(effectiveRPM);
        if (vibration) gpio_set_level(VIBRATION_PIN, 1);
        isDutyCycleActive = false;
    } 
    else {
        unsigned long currentMillis = millis();
        float dutyRatio = target / MIN_STABLE_RPM; 
        unsigned long onTime = (unsigned long)(DUTY_CYCLE_PERIOD_MS * dutyRatio);
        if (onTime > 0) onTime += STARTUP_LATENCY_MS;
        if (currentMillis - lastCycleStart >= DUTY_CYCLE_PERIOD_MS) lastCycleStart = currentMillis;
        if (currentMillis - lastCycleStart < onTime) {
            setMotorSpeed(MIN_STABLE_RPM);
            if (vibration) gpio_set_level(VIBRATION_PIN, 1);
            isDutyCycleActive = true;
        } else {
            setMotorSpeed(0);
        }
    }
}

// --- Setup ---
void setup() {
    Serial.begin(115200);
    
    // NEW: Load Saved Calibration
    preferences.begin("cal", false);
    FLOW_CURVE_A = preferences.getFloat("A", 15.0f); // Default 15.0 if not set
    FLOW_CURVE_B = preferences.getFloat("B", 1.0f);  // Default 1.0 if not set
    preferences.end();

    gpio_set_direction(BUTTON_PIN, GPIO_MODE_INPUT); 
    gpio_set_direction(TRIG_PIN, GPIO_MODE_INPUT);
    gpio_set_pull_mode(TRIG_PIN, GPIO_PULLUP_ONLY);
    gpio_set_direction(VIBRATION_PIN, GPIO_MODE_OUTPUT);
    gpio_set_level(VIBRATION_PIN, 0);
    gpio_set_direction(DIR_PIN, GPIO_MODE_OUTPUT);
    gpio_set_direction(EN_PIN, GPIO_MODE_OUTPUT);
    gpio_set_direction(STEP_PIN, GPIO_MODE_OUTPUT);
    gpio_set_level(EN_PIN, 0); 
    gpio_set_level(DIR_PIN, 1);

    setupMotorTimer();
    timer_enable_intr(TIMER_GROUP_0, TIMER_0);
    xTaskCreatePinnedToCore(loadCellTask, "LoadCell", 4096, NULL, 1, NULL, 1);
}

// --- Main Loop ---
void loop() {
    if (Serial.available() > 0) {
        String input = Serial.readStringUntil('\n');
        input.trim();

        if (input.startsWith("RPM:")) {
            targetRPM = input.substring(4).toFloat();
            serialControlActive = true;
        } 
        else if (input.startsWith("RATE:")) {
            float targetRate = input.substring(5).toFloat();
            targetRPM = calculateRPM(targetRate);
            serialControlActive = true;
            Serial.printf("Info: Rate %.2fg/s -> RPM %.2f (A=%.2f, B=%.2f)\n", targetRate, targetRPM, FLOW_CURVE_A, FLOW_CURVE_B);
        }
        // --- NEW: Calibration Command (CAL:15.5,1.1) ---
        else if (input.startsWith("CAL:")) {
            int commaIndex = input.indexOf(',');
            if (commaIndex > 0) {
                String valA = input.substring(4, commaIndex);
                String valB = input.substring(commaIndex + 1);
                FLOW_CURVE_A = valA.toFloat();
                FLOW_CURVE_B = valB.toFloat();
                
                // Save to Flash
                preferences.begin("cal", false);
                preferences.putFloat("A", FLOW_CURVE_A);
                preferences.putFloat("B", FLOW_CURVE_B);
                preferences.end();
                
                Serial.printf("Info: Calibration Updated. A=%.3f, B=%.3f\n", FLOW_CURVE_A, FLOW_CURVE_B);
            }
        }
        else if (input == "STOP") {
            targetRPM = 0;
            serialControlActive = false;
            gpio_set_level(VIBRATION_PIN, 0);
        }
        else if (input == "TARE") {
            tareRequested = true;
            Serial.println("System: Taring..."); 
        }
        else if (input == "VIB:1") { vibrationEnabled = true; }
        else if (input == "VIB:0") { vibrationEnabled = false; }
    }

    float activeRPM = 0.0f;
    bool activeVib = false;
    if (serialControlActive) {
        activeRPM = targetRPM;
        activeVib = vibrationEnabled;
    } else {
        bool triggerActive = (gpio_get_level(TRIG_PIN) == 0);
        if (triggerActive) {
            activeRPM = MOTOR_RPM;
            activeVib = true;
        }
    }
    manageMotorControl(activeRPM, activeVib);

    if (millis() - lastSerialPrint >= 100) {
        Serial.printf("Mass:%.2f,Rate:%.2f,RPM:%.0f\n", currentMass, currentRate, targetRPM);
        lastSerialPrint = millis();
    }
    vTaskDelay(pdMS_TO_TICKS(10)); 
}