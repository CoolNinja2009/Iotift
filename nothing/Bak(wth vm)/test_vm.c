#include <stdio.h>
#include <stdint.h>
#include <string.h>

// Include VM
#include "vm.h"

// Mock Arduino functions
#define HIGH 1
#define LOW 0
#define OUTPUT 1

void pinMode(int pin, int mode) {
    printf("pinMode(%d, %d)\n", pin, mode);
}

void digitalWrite(int pin, int value) {
    printf("digitalWrite(%d, %s)\n", pin, value ? "HIGH" : "LOW");
}

unsigned long millis() {
    static unsigned long time = 0;
    return time += 10; // Advance 10ms each call
}

void delay(int ms) {
    // Mock delay
}

void Serial_begin(int baud) {}
void Serial_println(int val) {
    printf("Serial: %d\n", val);
}

// Test bytecode: SET_PIN 12 1, SCHEDULE 12 0 500
const uint8_t test_bytecode[] = {
    0x01, 0x0c, 0x01,  // SET_PIN 12 1
    0x04, 0x0c, 0x00, 0x01, 0xf4  // SCHEDULE 12 0 500
};

int main() {
    printf("Testing IOTIFT VM\n");

    vm_init();
    vm_load_code(test_bytecode, sizeof(test_bytecode));

    // Setup
    pinMode(12, OUTPUT);

    // Simulate loop
    for (int i = 0; i < 10; i++) {
        printf("Loop %d:\n", i);
        run_vm_step();
        check_scheduler();
        delay(10);
    }

    return 0;
}