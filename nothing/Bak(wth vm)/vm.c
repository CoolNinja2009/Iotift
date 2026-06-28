#include "vm.h"

// VM State
uint8_t code[CODE_SIZE];
int vars[VAR_COUNT];
int stack[STACK_SIZE];
int pc = 0;
int sp = 0;

// Scheduler
ScheduledTask scheduler[16];

void vm_init() {
    pc = 0;
    sp = 0;
    memset(vars, 0, sizeof(vars));
    memset(stack, 0, sizeof(stack));
    memset(scheduler, 0, sizeof(scheduler));
    memset(code, 0, sizeof(code));
}

void vm_load_code(const uint8_t* bytecode, size_t size) {
    if (size > CODE_SIZE) size = CODE_SIZE;
    memcpy(code, bytecode, size);
    pc = 0;
}

void run_vm_step() {
    // Execute a few instructions per step to avoid blocking
    for (int i = 0; i < 5 && pc < CODE_SIZE; i++) {
        uint8_t opcode = code[pc++];
        switch (opcode) {
            case OP_SET_PIN: {
                uint8_t pin = code[pc++];
                uint8_t value = code[pc++];
                digitalWrite(pin, value ? HIGH : LOW);
                break;
            }
            case OP_SET_VAR: {
                uint8_t var_id = code[pc++];
                uint8_t value = code[pc++];
                vars[var_id] = value;
                break;
            }
            case OP_ADD_VAR: {
                uint8_t var_id = code[pc++];
                uint8_t value = code[pc++];
                vars[var_id] += value;
                break;
            }
            case OP_SCHEDULE: {
                uint8_t pin = code[pc++];
                uint8_t value = code[pc++];
                uint16_t delay = (code[pc] << 8) | code[pc + 1];
                pc += 2;
                schedule_after(pin, value, delay);
                break;
            }
            case OP_JMP: {
                uint16_t addr = (code[pc] << 8) | code[pc + 1];
                pc = addr;
                break;
            }
            case OP_JMP_IF_FALSE: {
                uint16_t addr = (code[pc] << 8) | code[pc + 1];
                pc += 2;
                int cond = stack[--sp];
                if (cond == 0) {
                    pc = addr;
                }
                break;
            }
            case OP_CMP_EQ: {
                uint8_t var_id = code[pc++];
                uint8_t value = code[pc++];
                int result = (vars[var_id] == value) ? 1 : 0;
                stack[sp++] = result;
                break;
            }
            case OP_CMP_GT: {
                uint8_t var_id = code[pc++];
                uint8_t value = code[pc++];
                int result = (vars[var_id] > value) ? 1 : 0;
                stack[sp++] = result;
                break;
            }
            case OP_CMP_LT: {
                uint8_t var_id = code[pc++];
                uint8_t value = code[pc++];
                int result = (vars[var_id] < value) ? 1 : 0;
                stack[sp++] = result;
                break;
            }
            case OP_PUSH_CONST: {
                uint8_t value = code[pc++];
                stack[sp++] = value;
                break;
            }
            case OP_PUSH_VAR: {
                uint8_t var_id = code[pc++];
                stack[sp++] = vars[var_id];
                break;
            }
            case OP_POP: {
                sp--;
                break;
            }
            case OP_PRINT_VAR: {
                uint8_t var_id = code[pc++];
                Serial.println(vars[var_id]);
                break;
            }
            default:
                // Unknown opcode, skip
                break;
        }
    }
}

void schedule_after(int pin, int value, unsigned long ms) {
    for (int i = 0; i < 16; i++) {
        if (!scheduler[i].active) {
            unsigned long now = millis();
            scheduler[i].trigger_time = now + ms;
            scheduler[i].pin = pin;
            scheduler[i].value = value;
            scheduler[i].active = 1;
            return;
        }
    }
}

void check_scheduler() {
    unsigned long now = millis();
    for (int i = 0; i < 16; i++) {
        if (scheduler[i].active && now >= scheduler[i].trigger_time) {
            digitalWrite(scheduler[i].pin, scheduler[i].value ? HIGH : LOW);
            scheduler[i].active = 0;
        }
    }
}</content>
<parameter name="filePath">c:\Users\cooln\Downloads\Iotift-V2\vm.c