#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <math.h>

// --- Configuration Constants ---
// Note: Pin definitions are kept to compile but not used physically
#define RATE_SAMPLE_INTERVAL_MS 100
#define RATE_WINDOW_SECONDS     1
#define HISTORY_SIZE            (RATE_WINDOW_SECONDS * 1000 / RATE_SAMPLE_INTERVAL_MS)
#define SMOOTHING_ALPHA 0.3 

// --- Global Variables ---
float massHistory[HISTORY_SIZE];
int historyIndex = 0;
bool bufferFull = false;

// --- VOLATILE VARIABLES (Shared between tasks) ---
volatile float currentMass = 0.0f;
volatile float currentRate = 0.0f;
volatile bool tareRequested = false;

// Control Globals
float targetRPM = 0.0f;
bool serialControlActive = false;
bool vibrationEnabled = true;

// --- Simulation Variables ---
float simulatedTotalMass = 0.0f; // Internal counter for the "physical" mass
float simulationFlowFactor = 0.05f; // How much mass adds per tick per RPM

// --- Mock Motor Control ---
// In the real code, this set timers. Here, it just confirms state.
void setMotorSpeed(float rpm) {
    // No physical pins to write
    // Just holding the RPM value is enough for our simulation logic
}

// --- Simulation Task (Replaces Load Cell Task) ---
// This generates fake sensor data behaving like the real rig
void simulationTask(void *pvParameters) {
    
    // Clear history
    for (int i = 0; i < HISTORY_SIZE; i++) massHistory[i] = 0.0f;
    
    float filteredReading = 0.0f;
    TickType_t xLastWakeTime = xTaskGetTickCount();
    const TickType_t xFrequency = pdMS_TO_TICKS(RATE_SAMPLE_INTERVAL_MS);

    while (true) {
        // 1. HANDLE TARE
        if (tareRequested) {
            simulatedTotalMass = 0.0f; // Reset physics
            filteredReading = 0.0f;
            currentMass = 0.0f;
            currentRate = 0.0f;
            for (int i = 0; i < HISTORY_SIZE; i++) massHistory[i] = 0.0f;
            tareRequested = false; 
        }

        // 2. SIMULATE PHYSICAL PROCESS (Filling)
        // If RPM > 0, we assume mass is increasing (e.g., a hopper filling)
        if (targetRPM > 0) {
            // Add mass based on RPM speed
            float massIncrease = targetRPM * simulationFlowFactor; 
            simulatedTotalMass += massIncrease;
        }

        // 3. GENERATE NOISE
        // Real load cells are noisy. We add +/- 0.5 unit random jitter
        float noise = (random(0, 100) / 100.0f) - 0.5f;
        float rawReading = simulatedTotalMass + noise;
        
        // Ensure we don't simulate negative mass for this test unless desired
        if (rawReading < 0) rawReading = 0;

        // 4. APPLY THE EXACT SAME FILTER LOGIC AS ORIGINAL
        filteredReading = (SMOOTHING_ALPHA * rawReading) + ((1.0 - SMOOTHING_ALPHA) * filteredReading);
        
        // Update Globals
        currentMass = filteredReading;

        // Rate Calculation
        float oldMass = massHistory[historyIndex];
        massHistory[historyIndex] = filteredReading;
        
        historyIndex = (historyIndex + 1) % HISTORY_SIZE;
        if (historyIndex == 0) bufferFull = true;
        
        if (bufferFull) {
            currentRate = (filteredReading - oldMass) / (float)RATE_WINDOW_SECONDS;
        }
        
        vTaskDelayUntil(&xLastWakeTime, xFrequency);
    }
}

// --- Setup ---
void setup() {
    Serial.begin(115200);
    
    // Initialize Random Seed
    randomSeed(analogRead(0));

    // Start the Simulation Task (Mocking the Load Cell)
    xTaskCreatePinnedToCore(simulationTask, "SimLoadCell", 4096, NULL, 1, NULL, 1);
    
    Serial.println("System: SIMULATION MODE STARTED");
    Serial.println("System: Ready for App Testing");
}

// --- Main Loop ---
void loop() {
    // 1. Read Serial Commands (Identical to original)
    if (Serial.available() > 0) {
        String input = Serial.readStringUntil('\n');
        input.trim(); 

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
            Serial.println("System: Taring..."); 
        }
        else if (input == "VIB:1") {
            vibrationEnabled = true;
        }
        else if (input == "VIB:0") {
            vibrationEnabled = false;
        }
    }

    // 2. Control Logic (Simplified for Simulation)
    if (serialControlActive) {
        setMotorSpeed(targetRPM);
    } else {
        // In sim mode, if we aren't controlled by serial, we just sit idle
        // (ignoring physical buttons)
        targetRPM = 0;
        setMotorSpeed(0);
    }

    // 3. Output Data (Identical format)
    Serial.printf("Mass:%.2f,Rate:%.2f,RPM:%.0f\n", currentMass, currentRate, targetRPM);
    
    vTaskDelay(pdMS_TO_TICKS(50));
}