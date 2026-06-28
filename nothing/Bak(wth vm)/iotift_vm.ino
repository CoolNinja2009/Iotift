#include "vm.h"
#include "generated.h"

void setup() {
    Serial.begin(115200);

    // Initialize VM
    vm_init();

    // Load bytecode
    vm_load_code(iotift_bytecode, iotift_bytecode_size);

    // Setup pins (this should be generated based on the program)
    pinMode(12, OUTPUT); // LED pin
}

unsigned long last_timer = 0;

void loop() {
    unsigned long now = millis();

    // Run timer logic every 1000ms - execute the bytecode
    if (now - last_timer >= 1000) {
        last_timer = now;
        // Reset PC to beginning for timer execution
        pc = 0;
        run_vm_step();
    }

    // Check scheduler for 'after' operations
    check_scheduler();

    // Small delay to prevent busy loop
    delay(10);
}