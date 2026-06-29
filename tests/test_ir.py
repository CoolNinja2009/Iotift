"""
IR tests — Milestone 2

Tests for:
  1. AST → IR lowering correctness
  2. Constant folding verification
  3. Dead code elimination verification
  4. Empty handler removal verification
  5. Redundant store elimination verification
  6. Full pipeline integration

All tests verify that the IR module is correctly generated from Iotift source
and that optimization passes produce the expected transformations.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from lexer import tokenize
from parser import Parser
from ir import (
    IRModule, IRFunction, IRGlobal, BasicBlock,
    IRBinary, IRUnary, IRCopy, IRCall, IRBranch, IRJump, IRReturn,
    IRCast, IRArrayAccess, IRMemberAccess,
    IRValue, _tv, _cv, _vv, _void,
)
from ir_lowering import IRLowering
from ir_optimizer import IROptimizer
from ir_codegen import IRCodeGen


# ─────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────

def lower(source: str) -> IRModule:
    """Parse and lower Iotift source to an IR module."""
    tokens = tokenize(source)
    ast = Parser(tokens).parse()
    return IRLowering().lower(ast)


def optimize(source: str) -> IRModule:
    """Parse, lower, and optimize Iotift source."""
    return IROptimizer(lower(source)).run_all()


def compile_ir(source: str) -> str:
    """Compile Iotift source through the full IR pipeline to C."""
    ir_mod = optimize(source)
    return IRCodeGen().generate(ir_mod)


def count_instructions(module: IRModule, instr_type=None) -> int:
    """Count instructions of a given type across all functions."""
    total = 0
    for fn in module.functions:
        for bb in fn.blocks:
            for instr in bb.instructions:
                if instr_type is None or isinstance(instr, instr_type):
                    total += 1
    return total


# ─────────────────────────────────────────
#  1. LOWERING CORRECTNESS
# ─────────────────────────────────────────

class TestLowering:
    """Test that AST → IR lowering produces correct IR."""

    def test_empty_program(self):
        """An empty program produces an empty module."""
        ir = lower("@device esp32\n")
        assert ir.device == 'esp32'
        assert len(ir.functions) == 0
        assert len(ir.globals) == 0

    def test_pin_decl(self):
        """Pin declarations should register in pin map."""
        ir = lower("@device esp32\npin LED = output 2;\n")
        assert 'LED' in ir.pins
        assert ir.pins['LED'] == 2

    def test_pwm_pin_decl(self):
        """PWM pins should allocate a channel."""
        ir = lower("@device esp32\npin R = pwm 13;\n")
        assert 'R' in ir.pwm_pins
        assert ir.pwm_pins['R']['channel'] == 0
        assert ir.pwm_pins['R']['number'] == 13

    def test_global_variable(self):
        """Old-style var declarations become IR globals."""
        ir = lower("@device esp32\nint count = 0;\n")
        assert len(ir.globals) == 1
        assert ir.globals[0].name == 'count'
        assert ir.globals[0].ctype == 'int'
        assert ir.globals[0].init == 0

    def test_let_variable(self):
        """let declarations become const globals."""
        ir = lower("@device esp32\nlet x = 42;\n")
        assert len(ir.globals) == 1
        g = ir.globals[0]
        assert g.name == 'x'
        assert g.is_const is True

    def test_struct_decl(self):
        """Struct declarations become IR structs."""
        ir = lower("""
@device esp32
struct Sensor {
    int id;
    float value;
}
""")
        assert len(ir.structs) == 1
        assert ir.structs[0].name == 'Sensor'
        assert len(ir.structs[0].fields) == 2

    def test_enum_decl(self):
        """Enum declarations become IR enums."""
        ir = lower("""
@device esp32
enum Mode { WarmWhite, Rainbow = 5 }
""")
        assert len(ir.enums) == 1
        assert ir.enums[0].name == 'Mode'
        assert len(ir.enums[0].variants) == 2

    def test_function_lowering(self):
        """Functions should be lowered to IR functions."""
        ir = lower("""
@device esp32
fn add(int a, int b) -> int {
    return a + b;
}
""")
        fns = [f for f in ir.functions if f.name == 'add']
        assert len(fns) == 1
        fn = fns[0]
        assert fn.return_type == 'int'
        assert len(fn.params) == 2
        assert fn.params[0].name == 'a'
        assert fn.params[1].name == 'b'
        # Should have at least one return instruction
        has_return = any(
            isinstance(instr, IRReturn)
            for bb in fn.blocks
            for instr in bb.instructions
        )
        assert has_return

    def test_every_block_lowering(self):
        """Every blocks become handler functions."""
        ir = lower("""
@device esp32
pin LED = output 2;
every 1000 { LED = 1; }
""")
        assert len(ir.every_handlers) == 1
        handler_fn = ir.every_handlers[0]
        assert 'every' in handler_fn['name']

    def test_empty_every_skipped(self):
        """Empty every blocks should not generate handlers."""
        ir = lower("""
@device esp32
every 100 { }
""")
        assert len(ir.every_handlers) == 0

    def test_on_event_handler(self):
        """on PIN.press should create an event handler."""
        ir = lower("""
@device esp32
pin BTN = input 5;
on BTN.press { print("pressed"); }
""")
        assert len(ir.on_event_handlers) == 1

    def test_tick_block(self):
        """tick blocks become _iotift_tick functions."""
        ir = lower("""
@device esp32
tick { print("tock"); }
""")
        fns = [f for f in ir.functions if f.name == '_iotift_tick']
        assert len(fns) == 1

    def test_assign_after_scheduler(self):
        """AssignAfter should enable the scheduler."""
        ir = lower("""
@device esp32
pin LED = output 2;
LED = 0 after 200;
""")
        assert ir.scheduler_needed

    def test_if_statement_creates_branches(self):
        """if statements should create branch instructions."""
        ir = lower("""
@device esp32
fn check(int x) {
    if (x > 5) {
        print("big");
    }
}
""")
        fns = [f for f in ir.functions if f.name == 'check']
        assert len(fns) == 1
        has_branch = any(
            isinstance(instr, IRBranch)
            for bb in fns[0].blocks
            for instr in bb.instructions
        )
        assert has_branch, "if statement should create branch instruction"

    def test_while_loop_creates_blocks(self):
        """while loops should create multiple basic blocks."""
        ir = lower("""
@device esp32
fn loop_fn() {
    int i = 0;
    while (i < 10) {
        i += 1;
    }
}
""")
        fns = [f for f in ir.functions if f.name == 'loop_fn']
        assert len(fns) == 1
        # Should have condition block, body block, and end block
        assert len(fns[0].blocks) >= 3

    def test_for_loop_creates_blocks(self):
        """for loops should create multiple basic blocks."""
        ir = lower("""
@device esp32
fn sum_fn() -> int {
    int total = 0;
    for (int i = 0; i < 10; i += 1) {
        total += i;
    }
    return total;
}
""")
        fns = [f for f in ir.functions if f.name == 'sum_fn']
        assert len(fns) == 1
        assert len(fns[0].blocks) >= 4  # init, cond, body, step, end

    def test_cast_expression(self):
        """Cast expressions generate IRCast instructions."""
        ir = lower("""
@device esp32
fn convert() -> u8 {
    int x = 300;
    return x as u8;
}
""")
        fns = [f for f in ir.functions if f.name == 'convert']
        assert len(fns) == 1
        has_cast = any(
            isinstance(instr, IRCast)
            for bb in fns[0].blocks
            for instr in bb.instructions
        )
        assert has_cast

    def test_sizeof_expression(self):
        """SizeOfExpr should lower to a constant."""
        ir = lower("""
@device esp32
int x = sizeof(u32);
""")
        assert len(ir.globals) >= 1

    def test_math_function_marks_module(self):
        """Using sin/cos should mark the module as using math."""
        ir = lower("""
@device esp32
fn calc() -> float {
    return sin(3.14);
}
""")
        assert ir.uses_math

    def test_c_block_injection(self):
        """C blocks should go to the appropriate section."""
        ir = lower("""
@device esp32
c header { #define FOO 1 }
c global { int shared; }
c setup { Serial.println("hi"); }
c loop { yield(); }
""")
        assert len(ir.header_blocks) >= 1
        assert len(ir.global_blocks) >= 1
        assert len(ir.setup_blocks) >= 1
        assert len(ir.loop_blocks) >= 1

    def test_device_decl(self):
        """@device should set the module device."""
        ir = lower("@device esp32\n")
        assert ir.device == 'esp32'


# ─────────────────────────────────────────
#  2. CONSTANT FOLDING
# ─────────────────────────────────────────

class TestConstantFolding:
    """Test that constant folding evaluates compile-time expressions."""

    def test_simple_addition(self):
        """1 + 2 should fold to 3."""
        module = IRModule()
        fn = IRFunction(name='test', return_type='int', entry_block='entry')
        fn.new_block('entry')
        dest = module.new_temp('t', 'int')
        a = _cv(1, 'int')
        b = _cv(2, 'int')
        fn.blocks[0].append(IRBinary('+', a, b, dest))
        module.add_function(fn)

        opt = IROptimizer(module)
        opt.constant_folding()

        # The binary should be replaced with a copy from constant
        instrs = fn.blocks[0].instructions
        assert len(instrs) == 1
        assert isinstance(instrs[0], IRCopy)
        assert instrs[0].src.const_value == 3

    def test_subtraction_folds(self):
        """5 - 3 should fold to 2."""
        module = IRModule()
        fn = IRFunction(name='test', return_type='int', entry_block='entry')
        fn.new_block('entry')
        dest = module.new_temp('t', 'int')
        fn.blocks[0].append(IRBinary('-', _cv(5), _cv(3), dest))
        module.add_function(fn)

        IROptimizer(module).constant_folding()

        instrs = fn.blocks[0].instructions
        assert isinstance(instrs[0], IRCopy)
        assert instrs[0].src.const_value == 2

    def test_multiplication_folds(self):
        """4 * 7 should fold to 28."""
        module = IRModule()
        fn = IRFunction(name='test', return_type='int', entry_block='entry')
        fn.new_block('entry')
        dest = module.new_temp('t', 'int')
        fn.blocks[0].append(IRBinary('*', _cv(4), _cv(7), dest))
        module.add_function(fn)

        IROptimizer(module).constant_folding()

        instrs = fn.blocks[0].instructions
        assert isinstance(instrs[0], IRCopy)
        assert instrs[0].src.const_value == 28

    def test_division_folds(self):
        """10 / 2 should fold to 5."""
        module = IRModule()
        fn = IRFunction(name='test', return_type='int', entry_block='entry')
        fn.new_block('entry')
        dest = module.new_temp('t', 'int')
        fn.blocks[0].append(IRBinary('/', _cv(10), _cv(2), dest))
        module.add_function(fn)

        IROptimizer(module).constant_folding()

        instrs = fn.blocks[0].instructions
        assert isinstance(instrs[0], IRCopy)
        assert instrs[0].src.const_value == 5

    def test_division_by_zero_not_folded(self):
        """x / 0 should NOT be folded (preserve original instruction)."""
        module = IRModule()
        fn = IRFunction(name='test', return_type='int', entry_block='entry')
        fn.new_block('entry')
        dest = module.new_temp('t', 'int')
        fn.blocks[0].append(IRBinary('/', _cv(10), _cv(0), dest))
        module.add_function(fn)

        IROptimizer(module).constant_folding()

        instrs = fn.blocks[0].instructions
        assert isinstance(instrs[0], IRBinary)  # Not folded

    def test_boolean_folding(self):
        """true && false should fold to false."""
        module = IRModule()
        fn = IRFunction(name='test', return_type='bool', entry_block='entry')
        fn.new_block('entry')
        dest = module.new_temp('t', 'bool')
        fn.blocks[0].append(IRBinary('&&', _cv(1, 'bool'), _cv(0, 'bool'), dest))
        module.add_function(fn)

        IROptimizer(module).constant_folding()

        instrs = fn.blocks[0].instructions
        assert isinstance(instrs[0], IRCopy)
        assert instrs[0].src.const_value == 0

    def test_unary_minus_folds(self):
        """-42 should fold to -42."""
        module = IRModule()
        fn = IRFunction(name='test', return_type='int', entry_block='entry')
        fn.new_block('entry')
        dest = module.new_temp('t', 'int')
        fn.blocks[0].append(IRUnary('-', _cv(42), dest))
        module.add_function(fn)

        IROptimizer(module).constant_folding()

        instrs = fn.blocks[0].instructions
        assert isinstance(instrs[0], IRCopy)
        assert instrs[0].src.const_value == -42

    def test_branch_always_true(self):
        """A branch with constant true condition should become unconditional jump."""
        module = IRModule()
        fn = IRFunction(name='test', return_type='void', entry_block='entry')
        fn.new_block('entry')
        fn.blocks[0].append(IRBranch(_cv(1, 'bool'), true_label='L1', false_label='L2'))
        fn.new_block('L1')
        fn.new_block('L2')
        module.add_function(fn)

        IROptimizer(module).constant_folding()

        instrs = fn.blocks[0].instructions
        assert isinstance(instrs[0], IRJump)
        assert instrs[0].label == 'L1'

    def test_branch_always_false(self):
        """A branch with constant false condition should jump to false label."""
        module = IRModule()
        fn = IRFunction(name='test', return_type='void', entry_block='entry')
        fn.new_block('entry')
        fn.blocks[0].append(IRBranch(_cv(0, 'bool'), true_label='L1', false_label='L2'))
        fn.new_block('L1')
        fn.new_block('L2')
        module.add_function(fn)

        IROptimizer(module).constant_folding()

        instrs = fn.blocks[0].instructions
        assert isinstance(instrs[0], IRJump)
        assert instrs[0].label == 'L2'

    def test_folding_on_real_source(self):
        """Constant folding should work on lowered IR from source code."""
        ir = lower("""
@device esp32
fn fold_test() -> int {
    return 1 + 2;
}
""")
        IROptimizer(ir).constant_folding()
        fns = [f for f in ir.functions if f.name == 'fold_test']
        assert len(fns) == 1
        # Should have folded 1+2 and returned constant
        has_return = any(
            isinstance(instr, IRReturn) and instr.value is not None
            for bb in fns[0].blocks
            for instr in bb.instructions
        )
        assert has_return


# ─────────────────────────────────────────
#  3. DEAD CODE ELIMINATION
# ─────────────────────────────────────────

class TestDCE:
    """Test that dead code elimination removes unreachable blocks."""

    def test_unreachable_block_removed(self):
        """A block with no predecessors should be removed."""
        module = IRModule()
        fn = IRFunction(name='test', return_type='void', entry_block='entry')
        fn.new_block('entry')
        fn.blocks[-1].append(IRJump('end'))
        fn.new_block('end')
        fn.blocks[-1].append(IRReturn())
        fn.new_block('unreachable')
        fn.blocks[-1].append(IRReturn())
        module.add_function(fn)

        IROptimizer(module).dead_code_elimination()

        labels = {bb.label for bb in fn.blocks}
        assert 'unreachable' not in labels

    def test_all_blocks_reachable(self):
        """When all blocks are reachable, none should be removed."""
        module = IRModule()
        fn = IRFunction(name='test', return_type='void', entry_block='entry')
        fn.new_block('entry')
        fn.blocks[-1].append(IRBranch(_cv(1, 'bool'), 'then', 'end'))
        fn.new_block('then')
        fn.blocks[-1].append(IRJump('end'))
        fn.new_block('end')
        fn.blocks[-1].append(IRReturn())
        module.add_function(fn)

        original_count = len(fn.blocks)
        IROptimizer(module).dead_code_elimination()
        assert len(fn.blocks) == original_count


# ─────────────────────────────────────────
#  4. EMPTY HANDLER REMOVAL
# ─────────────────────────────────────────

class TestEmptyHandlerRemoval:
    """Test that handlers with empty bodies are removed."""

    def test_empty_every_removed(self):
        """Empty every blocks should be removed from handler list."""
        ir = optimize("""
@device esp32
every 100 { }
every 500 { print("ok"); }
""")
        assert len(ir.every_handlers) == 1

    def test_non_empty_every_kept(self):
        """Non-empty every blocks should be kept."""
        ir = optimize("""
@device esp32
pin LED = output 2;
every 500 { LED = 1; }
""")
        assert len(ir.every_handlers) == 1


# ─────────────────────────────────────────
#  5. FULL PIPELINE TESTS
# ─────────────────────────────────────────

class TestFullPipeline:
    """End-to-end tests from source to generated C via IR."""

    def test_blink_program(self):
        """A blink program should compile through the IR pipeline."""
        c = compile_ir("""
@device esp32
pin LED = output 2;
every 1000 { LED = !LED; }
""")
        assert '#include <Arduino.h>' in c
        assert 'LED_PIN' in c
        assert 'void loop' in c
        assert 'yield()' in c
        assert 'every' in c  # handler function name

    def test_pwm_program(self):
        """PWM programs should generate LEDC calls."""
        c = compile_ir("""
@device esp32
pin R = pwm 13;
R.setup(1000, 10);
every 10 { R.write(128); }
""")
        assert 'ledcSetup' in c
        assert 'ledcAttachPin' in c
        assert 'ledcWrite' in c

    def test_button_event(self):
        """Button events should generate handlers."""
        c = compile_ir("""
@device esp32
pin LED = output 2;
pin BTN = input 5;
on BTN.press { LED = !LED; }
""")
        assert 'BTN_PIN' in c
        # The on-event handler should be in the output
        assert '_iotift_on_' in c

    def test_timer_with_label(self):
        """Named timers should use stable names."""
        c = compile_ir("""
@device esp32
every 1000 as blinker {
    print("tick");
}
""")
        assert '_iotift_every_blinker' in c

    def test_after_assign_scheduler(self):
        """Deferred assignment should include scheduler."""
        c = compile_ir("""
@device esp32
pin LED = output 2;
LED = 0 after 200;
""")
        assert '_iotift_schedule_pin' in c
        assert '_iotift_scheduler_tick' in c

    def test_enum_emission(self):
        """Enums should emit typedef enum."""
        c = compile_ir("""
@device esp32
enum Mode { WarmWhite, Rainbow = 5 }
""")
        assert 'typedef enum' in c
        assert 'Mode' in c

    def test_volatile_variable(self):
        """volatile modifier should appear in output."""
        c = compile_ir("""
@device esp32
volatile int flags = 0;
""")
        assert 'volatile' in c

    def test_isr_function(self):
        """ISR functions should have IRAM_ATTR."""
        c = compile_ir("""
@device esp32
isr fn on_timer() {
    count = count + 1;
}
""")
        assert 'IRAM_ATTR' in c

    def test_struct_emission(self):
        """Structs should be emitted."""
        c = compile_ir("""
@device esp32
struct Sensor { int id; float value; }
""")
        assert 'struct Sensor' in c

    def test_math_include(self):
        """Math functions should trigger math.h include."""
        c = compile_ir("""
@device esp32
fn calc() -> float {
    return sin(1.0);
}
""")
        assert '#include <math.h>' in c

    def test_global_const_pin(self):
        """Pins should use static const, not #define."""
        c = compile_ir("""
@device esp32
pin LED = output 2;
""")
        assert 'static const uint8_t LED_PIN' in c
        assert '#define LED_PIN' not in c

    def test_tick_block(self):
        """tick block generates loop call."""
        c = compile_ir("""
@device esp32
tick { print("tock"); }
""")
        assert '_iotift_tick' in c

    def test_empty_handler_skipped(self):
        """Empty every blocks should not generate handlers."""
        c = compile_ir("""
@device esp32
every 100 { }
""")
        # Should not contain a handler function
        assert 'static void _iotift_every_' not in c


# ─────────────────────────────────────────
#  6. OPTIMIZER CORRECTNESS
# ─────────────────────────────────────────

class TestOptimizerCorrectness:
    """Verify that optimized output is functionally equivalent."""

    def test_constant_folding_preserves_struct(self):
        """Optimized IR should still have valid structure."""
        ir = optimize("""
@device esp32
fn test_fn() -> int {
    return 2 + 3;
}
""")
        fns = [f for f in ir.functions if f.name == 'test_fn']
        assert len(fns) == 1
        # Should still have at least one block
        assert len(fns[0].blocks) >= 1

    def test_optimized_output_compiles(self):
        """Optimized output should still be valid C code."""
        c = compile_ir("""
@device esp32
pin LED = output 2;
every 500 { LED = 1; }
""")
        assert 'void setup' in c
        assert 'void loop' in c
        assert '#include <Arduino.h>' in c

    def test_redundant_store_removal(self):
        """Back-to-back stores to same variable should collapse."""
        module = IRModule()
        fn = IRFunction(name='test', return_type='void', entry_block='entry')
        fn.new_block('entry')
        x = _vv('x', 'int')
        fn.blocks[0].append(IRCopy(_cv(5), x))
        fn.blocks[0].append(IRCopy(_cv(10), x))
        fn.blocks[0].append(IRReturn())
        module.add_function(fn)

        IROptimizer(module).redundant_store_elimination()

        # The first store (x=5) should be removed
        copies = [
            instr for instr in fn.blocks[0].instructions
            if isinstance(instr, IRCopy)
        ]
        assert len(copies) == 1
        assert copies[0].src.const_value == 10

    def test_dce_removes_dead_functions(self):
        """Functions with no effect should be removed."""
        module = IRModule()
        fn = IRFunction(name='empty', return_type='void', entry_block='entry')
        fn.new_block('entry')
        fn.blocks[0].append(IRReturn())
        module.add_function(fn)

        IROptimizer(module).dead_code_elimination()

        # The empty function should be removed
        assert len(module.functions) == 0


# ─────────────────────────────────────────
#  7. CONSOLE_RGB INTEGRATION
# ─────────────────────────────────────────

class TestConsoleRGB:
    """Full pipeline test with the console_rgb.iot example."""

    def test_console_rgb_compiles(self):
        """console_rgb.iot should compile through IR pipeline."""
        try:
            with open(
                os.path.join(os.path.dirname(os.path.dirname(__file__)),
                             'examples', 'console_rgb.iot'),
                encoding='utf-8',
            ) as f:
                source = f.read()
        except FileNotFoundError:
            pytest.skip("console_rgb.iot not found")

        tokens = tokenize(source)
        ast = Parser(tokens).parse()
        ir = IRLowering().lower(ast)
        IROptimizer(ir).run_all()
        c = IRCodeGen().generate(ir)

        assert '#include <Arduino.h>' in c
        assert 'void setup' in c
        assert 'void loop' in c


# ─────────────────────────────────────────
#  8. DIRECT CODEGEN BACKWARD COMPAT
# ─────────────────────────────────────────

class TestDirectCodegenStillWorks:
    """Verify that --direct-codegen still produces good output."""

    def test_direct_blink(self):
        """Direct codegen should still work for blink."""
        from codegen import CodeGen

        source = """
@device esp32
pin LED = output 2;
every 1000 { LED = !LED; }
"""
        tokens = tokenize(source)
        ast = Parser(tokens).parse()
        c = CodeGen().generate(ast)

        assert '#include <Arduino.h>' in c
        assert 'LED_PIN' in c
        assert 'void loop' in c
