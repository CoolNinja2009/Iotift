"""
IOTIFT Bytecode Generator
Generates bytecode for the IOTIFT VM targeting ESP32 Arduino framework.
"""

from ast_nodes import *
from typing import List, Any, Dict
import struct

# Bytecode Opcodes
OPCODES = {
    'SET_PIN': 0x01,
    'SET_VAR': 0x02,
    'ADD_VAR': 0x03,
    'SCHEDULE': 0x04,
    'JMP': 0x10,
    'JMP_IF_FALSE': 0x11,
    'CMP_EQ': 0x20,
    'CMP_GT': 0x21,
    'CMP_LT': 0x22,
    'PUSH_CONST': 0x30,
    'PUSH_VAR': 0x31,
    'POP': 0x32,
    'PRINT_VAR': 0x40,
}

class BytecodeGen:
    def __init__(self):
        self.bytecode = bytearray()
        self.labels = {}  # label -> address
        self.pending_jumps = []  # (label, position_to_patch)
        self.pins = {}  # pin_name -> pin_number
        self.vars = {}  # var_name -> var_id
        self.var_counter = 0
        self.scheduler_needed = False

    def emit_byte(self, byte: int):
        self.bytecode.append(byte)

    def emit_word(self, word: int):
        # Emit 16-bit word in big-endian
        self.bytecode.extend(struct.pack('>H', word))

    def create_label(self, label: str):
        self.labels[label] = len(self.bytecode)

    def emit_jmp(self, opcode: int, label: str):
        self.emit_byte(opcode)
        # Reserve space for address
        pos = len(self.bytecode)
        self.emit_word(0)  # placeholder
        self.pending_jumps.append((label, pos))

    def resolve_jumps(self):
        for label, pos in self.pending_jumps:
            if label not in self.labels:
                raise ValueError(f"Undefined label: {label}")
            addr = self.labels[label]
            # Patch the address
            struct.pack_into('>H', self.bytecode, pos, addr)

    def get_var_id(self, name: str) -> int:
        if name not in self.vars:
            self.vars[name] = self.var_counter
            self.var_counter += 1
        return self.vars[name]

    def generate(self, program: Program) -> bytes:
        # Collect pins and vars
        for node in program.body:
            if isinstance(node, PinDecl):
                self.pins[node.name] = node.number
            elif isinstance(node, VarDecl):
                self.get_var_id(node.name)

        # Generate bytecode for each section
        main_bytecode = self.generate_main(program)

        return bytes(main_bytecode)

    def generate_main(self, program: Program) -> bytearray:
        self.bytecode = bytearray()
        self.pending_jumps = []

        for node in program.body:
            if isinstance(node, EveryBlock):
                # Generate the body of the every block
                for stmt in node.body:
                    self.generate_stmt(stmt)

        self.resolve_jumps()
        return self.bytecode

    def generate_stmt(self, node: Node):
        if isinstance(node, Assign):
            if node.target in self.pins:
                # SET_PIN pin value
                pin_num = self.pins[node.target]
                if isinstance(node.value, Literal) and node.value.vtype == 'int':
                    value = node.value.value
                    self.emit_byte(OPCODES['SET_PIN'])
                    self.emit_byte(pin_num)
                    self.emit_byte(value)
            else:
                # SET_VAR var_id value
                var_id = self.get_var_id(node.target)
                if isinstance(node.value, Literal) and node.value.vtype == 'int':
                    value = node.value.value
                    self.emit_byte(OPCODES['SET_VAR'])
                    self.emit_byte(var_id)
                    self.emit_byte(value)

        elif isinstance(node, AssignAfter):
            # SCHEDULE pin value delay
            pin_num = self.pins[node.target]
            if isinstance(node.value, Literal) and node.value.vtype == 'int':
                value = node.value.value
                delay = node.delay
                self.emit_byte(OPCODES['SCHEDULE'])
                self.emit_byte(pin_num)
                self.emit_byte(value)
                self.emit_word(delay)
            self.scheduler_needed = True

        elif isinstance(node, CompoundAssign):
            if node.op == '+=':
                var_id = self.get_var_id(node.target)
                if isinstance(node.value, Literal) and node.value.vtype == 'int':
                    value = node.value.value
                    self.emit_byte(OPCODES['ADD_VAR'])
                    self.emit_byte(var_id)
                    self.emit_byte(value)