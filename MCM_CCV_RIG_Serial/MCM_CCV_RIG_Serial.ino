#include <driver/rmt.h>
#include "driver/gpio.h"
#include "driver/timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include <math.h>
#include "HX711.h"

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

#define MICROSTEPS 400
#define MOTOR_RPM  80.0f  // Default Manual Speed

// Load Cell Settings
#define RATE_SAMPLE_INTERVAL_MS 100
#define RATE_WINDOW_SECONDS     1
#define HISTORY_SIZE            (RATE_WINDOW_SECONDS * 1000 / RATE_SAMPLE_INTERVAL_MS)
#define SMOOTHING_ALPHA 0.3 // Valid range: 0.01 (very smooth, slow) to 1.0 (no filtering, instant)

// --- Global Variables ---
HX711 scale;
float massHistory[HISTORY_SIZE];
int historyIndex = 0;
bool bufferFull = false;

// Calibration - Update this if needed
float calibration_factor = 45.31945101751073f;

// --- VOLATILE VARIABLES (Critical for Task Communication) ---
volatile bool motorRunning = false;
volatile bool motorStepLevel = false;
volatile float currentMass = 0.0f;
volatile float currentRate = 0.0f;
volatile bool tareRequested = false; // <--- This MUST be volatile

// Control Globals
float targetRPM = 0.0f;
bool serialControlActive = false;
bool vibrationEnabled = true;




// --- Timer Interrupt for Motor Stepping ---
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
        .divider     = 80  // 1us tick
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

    // Clear history
    for (int i = 0; i < HISTORY_SIZE; i++) massHistory[i] = 0.0f;

    // Initialize the filter with 0
    float filteredReading = 0.0f;

    TickType_t xLastWakeTime = xTaskGetTickCount();
    const TickType_t xFrequency = pdMS_TO_TICKS(RATE_SAMPLE_INTERVAL_MS);

    while (true) {
        // --- HANDLE TARE ---
        if (tareRequested) {
            scale.tare(); 
            // Reset everything including the filter
            filteredReading = 0.0f;
            currentMass = 0.0f;
            currentRate = 0.0f;
            for (int i = 0; i < HISTORY_SIZE; i++) massHistory[i] = 0.0f;
            tareRequested = false; 
        }

        // --- READ & FILTER ---
        if (scale.is_ready()) {
            float rawReading = scale.get_units(1); // Get fast raw sample
            if (rawReading < 1){
              rawReading = 0;
            } else{ rawReading += 1; }
            
            // --- THE MATH TRICK (Exponential Smoothing) ---
            // New Filtered Value = (Factor * New Raw) + ((1 - Factor) * Old Filtered)
            // If raw jumps from 100 to 105, filtered only goes to 101 (if alpha is 0.2)
            filteredReading = (SMOOTHING_ALPHA * rawReading) + ((1.0 - SMOOTHING_ALPHA) * filteredReading);

            // Update the global variable that the Python App sees
            currentMass = filteredReading;
            
            // Use the FILTERED value for rate calculation (stabilizes rate too!)
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
// --- Setup ---
void setup() {
    Serial.begin(115200);
    
    // Pins
    gpio_set_direction(BUTTON_PIN, GPIO_MODE_INPUT); 
    gpio_set_direction(TRIG_PIN, GPIO_MODE_INPUT);
    gpio_set_pull_mode(TRIG_PIN, GPIO_PULLUP_ONLY);
    
    gpio_set_direction(VIBRATION_PIN, GPIO_MODE_OUTPUT);
    gpio_set_level(VIBRATION_PIN, 0);

    gpio_set_direction(DIR_PIN, GPIO_MODE_OUTPUT);
    gpio_set_direction(EN_PIN, GPIO_MODE_OUTPUT);
    gpio_set_direction(STEP_PIN, GPIO_MODE_OUTPUT);
    gpio_set_level(EN_PIN, 0); // Enable Motor
    gpio_set_level(DIR_PIN, 1);

    setupMotorTimer();
    timer_enable_intr(TIMER_GROUP_0, TIMER_0);

    // Start Task
    xTaskCreatePinnedToCore(loadCellTask, "LoadCell", 4096, NULL, 1, NULL, 1);
}

// --- Main Loop ---
void loop() {
    // 1. Read Serial Commands
    if (Serial.available() > 0) {
        String input = Serial.readStringUntil('\n');
        input.trim(); // Remove \r and whitespace

        if (input.startsWith("RPM:")) {
            targetRPM = input.substring(4).toFloat();
            serialControlActive = true;
        } 
        else if (input == "STOP") {
            targetRPM = 0;
            serialControlActive = false;
        }
        else if (input == "TARE") {
            tareRequested = true; 
            Serial.println("System: Taring..."); // ACK to user
        }
        else if (input == "VIB:1") {
            vibrationEnabled = true;
        }
        else if (input == "VIB:0") {
            vibrationEnabled = false;
        }
    }

    // 2. Control Logic
    if (serialControlActive) {
        if (targetRPM > 0 && vibrationEnabled) {
             gpio_set_level(VIBRATION_PIN, 1);
        } else {
             gpio_set_level(VIBRATION_PIN, 0);
        }
        setMotorSpeed(targetRPM);
    } else {
        // Manual Mode
        bool active = (gpio_get_level(TRIG_PIN) == 0);
        if (active) {
            gpio_set_level(VIBRATION_PIN, 1);
            targetRPM = MOTOR_RPM;
            setMotorSpeed(targetRPM);
        } else {
            gpio_set_level(VIBRATION_PIN, 0);
            targetRPM = 0;
            setMotorSpeed(0);
        }
    }

    // 3. Output Data
    // Note: If tare is happening, mass might briefly be 0 or erratic, which is fine
    Serial.printf("Mass:%.2f,Rate:%.2f,RPM:%.0f\n", currentMass, currentRate, targetRPM);
    
    vTaskDelay(pdMS_TO_TICKS(50));
}