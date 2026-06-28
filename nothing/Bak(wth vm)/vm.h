#ifndef IOTIFT_VM_H
#define IOTIFT_VM_H

#include <stdint.h>
#include <Arduino.h>

// VM Configuration
#define CODE_SIZE 256
#define VAR_COUNT 32
#define STACK_SIZE 32

// Opcodes
#define OP_SET_PIN 0x01
#define OP_SET_VAR 0x02
#define OP_ADD_VAR 0x03
#define OP_SCHEDULE 0x04
#define OP_JMP 0x10
#define OP_JMP_IF_FALSE 0x11
#define OP_CMP_EQ 0x20
#define OP_CMP_GT 0x21
#define OP_CMP_LT 0x22
#define OP_PUSH_CONST 0x30
#define OP_PUSH_VAR 0x31
#define OP_POP 0x32
#define OP_PRINT_VAR 0x40

// VM State
extern uint8_t code[CODE_SIZE];
extern int vars[VAR_COUNT];
extern int stack[STACK_SIZE];
extern int pc;
extern int sp;

// Scheduler for 'after' operations
struct ScheduledTask {
    unsigned long trigger_time;
    int pin;
    int value;
    int active;
};

extern ScheduledTask scheduler[16];

// VM Functions
void vm_init();
void vm_load_code(const uint8_t* bytecode, size_t size);
void run_vm_step();
void schedule_after(int pin, int value, unsigned long ms);
void check_scheduler();

#endif</content>
<parameter name="filePath">c:\Users\cooln\Downloads\Iotift-V2\vm.h