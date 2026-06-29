"""
Parser tests - 20+ tests covering all declaration, statement, and expression types.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from lexer import tokenize
from parser import Parser, ParseError
from ast_nodes import *


def parse(source):
    return Parser(tokenize(source)).parse()

def parse_expect_errors(source):
    parser = Parser(tokenize(source))
    ast = parser.parse()
    return ast, parser._had_error

def test_pin_decl():
    prog = parse("pin LED = output 2;")
    pin = prog.body[0]
    assert isinstance(pin, PinDecl)
    assert pin.name == "LED"
    assert pin.direction == "output"
    assert pin.number == 2

def test_pin_with_config():
    prog = parse("pin BTN = input 5 { pull: up, debounce: 50ms };")
    pin = prog.body[0]
    assert isinstance(pin, PinDecl)
    assert pin.config.pull == "up"
    assert pin.config.debounce_ms == 50

def test_var_decl_old_style():
    prog = parse("int count = 0;")
    var = prog.body[0]
    assert isinstance(var, VarDecl)
    assert var.name == "count"
    assert var.init.value == 0

def test_var_decl_new_style_let():
    prog = parse("let x = 42;")
    var = prog.body[0]
    assert isinstance(var, VarDecl)
    assert var.name == "x"
    assert var.is_mutable == False

def test_var_decl_new_style_var():
    prog = parse("var y: u32 = 100;")
    var = prog.body[0]
    assert isinstance(var, VarDecl)
    assert var.vtype == "u32"

def test_var_decl_const():
    prog = parse("const int MAX = 100;")
    var = prog.body[0]
    assert var.is_const == True

def test_var_decl_volatile():
    prog = parse("volatile int flags = 0;")
    var = prog.body[0]
    assert var.is_volatile == True

def test_array_decl():
    prog = parse("int vals[10];")
    arr = prog.body[0]
    assert isinstance(arr, ArrayDecl)
    assert arr.size == 10

def test_struct_decl():
    prog = parse("struct Sensor { int id; float value; }")
    st = prog.body[0]
    assert isinstance(st, StructDecl)
    assert st.name == "Sensor"
    assert len(st.fields) == 2

def test_enum_decl():
    prog = parse("enum Mode { WarmWhite, Rainbow = 5, Breathing }")
    en = prog.body[0]
    assert isinstance(en, EnumDecl)
    assert en.name == "Mode"
    assert len(en.variants) == 3

def test_fn_decl():
    prog = parse("fn add(int a, int b) -> int { return a + b; }")
    fn = prog.body[0]
    assert isinstance(fn, FnDecl)
    assert fn.name == "add"
    assert fn.return_type == "int"

def test_isr_fn_decl():
    prog = parse("isr fn on_timer() { count = count + 1; }")
    fn = prog.body[0]
    assert fn.is_isr == True

def test_device_decl():
    prog = parse("@device esp32")
    dev = prog.body[0]
    assert isinstance(dev, DeviceDecl)
    assert dev.name == "esp32"

def test_if_statement():
    prog = parse("fn f() { if (x > 0) { return 1; } else { return 0; } }")
    fn = prog.body[0]
    stmt = fn.body[0]
    assert isinstance(stmt, IfStmt)
    assert stmt.else_body is not None

def test_while_loop():
    prog = parse("fn f() { while (x < 10) { x = x + 1; } }")
    fn = prog.body[0]
    assert isinstance(fn.body[0], WhileStmt)

def test_for_loop():
    prog = parse("fn f() { for (int i = 0; i < 10; i = i + 1) { print(i); } }")
    fn = prog.body[0]
    assert isinstance(fn.body[0], ForStmt)

def test_return_statement():
    prog = parse("fn f() -> int { return 42; }")
    fn = prog.body[0]
    assert isinstance(fn.body[0], ReturnStmt)

def test_break_continue():
    prog = parse("fn f() { loop { break; continue; } }")
    fn = prog.body[0]
    loop = fn.body[0]
    assert isinstance(loop.body[0], BreakStmt)
    assert isinstance(loop.body[1], ContinueStmt)

def test_print_statement():
    prog = parse('print("hello");')
    stmt = prog.body[0]
    assert isinstance(stmt, PrintStmt)

def test_stop_statement():
    prog = parse("every 1000 as blinker { stop blinker; }")
    every = prog.body[0]
    assert isinstance(every.body[0], StopStmt)

def test_defer_statement():
    prog = parse("fn f() { defer { cleanup(); } int x = 1; }")
    fn = prog.body[0]
    assert isinstance(fn.body[0], DeferStmt)

def test_tick_block():
    prog = parse("tick { STATUS = !STATUS; }")
    tick = prog.body[0]
    assert isinstance(tick, TickBlock)

def test_on_event():
    prog = parse("on BTN.press { LED = 1; }")
    evt = prog.body[0]
    assert isinstance(evt, OnEvent)
    assert evt.pin == "BTN"
    assert evt.event == "press"

def test_on_threshold():
    prog = parse('on TEMP > 50.0 { print("hot"); }')
    evt = prog.body[0]
    assert isinstance(evt, OnThreshold)

def test_every_block():
    prog = parse("every 500ms as blinker { LED = !LED; }")
    ev = prog.body[0]
    assert isinstance(ev, EveryBlock)
    assert ev.interval == 500
    assert ev.label == "blinker"

def test_binary_expression():
    prog = parse("int x = a + b * 2;")
    var = prog.body[0]
    assert isinstance(var.init, BinOp)

def test_unary_expression():
    prog = parse("int x = -count;")
    var = prog.body[0]
    assert isinstance(var.init, UnaryOp)

def test_member_access():
    prog = parse("int x = sensor.value;")
    var = prog.body[0]
    assert isinstance(var.init, MemberAccess)

def test_fn_call():
    prog = parse("blink(3);")
    call = prog.body[0]
    assert isinstance(call, FnCall)
    assert call.name == "blink"

def test_cast_expression():
    prog = parse("int x = val as u8;")
    var = prog.body[0]
    assert isinstance(var.init, CastExpr)

def test_sizeof_expression():
    prog = parse("int x = sizeof(i32);")
    var = prog.body[0]
    assert isinstance(var.init, SizeOfExpr)

def test_after_assign():
    prog = parse("LED = 0 after 200;")
    aa = prog.body[0]
    assert isinstance(aa, AssignAfter)
    assert aa.delay == 200

def test_error_recovery():
    prog, had_err = parse_expect_errors("int x = ; int y = 1;")
    assert had_err == True
    assert any(isinstance(n, VarDecl) and n.name == "y" for n in prog.body)

def test_void_loop_deprecated():
    prog = parse("void loop() { LED = 1; }")
    loop = prog.body[0]
    assert isinstance(loop, VoidLoop)


# ── Phase 1: Milestone 3 syntax extensions ──

def test_after_block():
    prog = parse("after 5s { print(\"fired\"); }")
    ab = prog.body[0]
    assert isinstance(ab, AfterBlock)
    assert ab.interval == 5000  # 5s = 5000ms
    assert len(ab.body) == 1

def test_after_block_with_small_delay():
    prog = parse("after 100ms { LED = 1; }")
    ab = prog.body[0]
    assert isinstance(ab, AfterBlock)
    assert ab.interval == 100

def test_every_with_offset():
    prog = parse("every 1s offset 100ms { LED = 1; }")
    eb = prog.body[0]
    assert isinstance(eb, EveryBlock)
    assert eb.interval == 1000
    assert eb.offset_ms == 100

def test_every_no_offset():
    """existing syntax without offset should still work"""
    prog = parse("every 500ms { LED = 1; }")
    eb = prog.body[0]
    assert isinstance(eb, EveryBlock)
    assert eb.interval == 500
    assert eb.offset_ms is None

def test_every_with_label_and_offset():
    prog = parse("every 2s as blinker offset 200ms { LED = 1; }")
    eb = prog.body[0]
    assert isinstance(eb, EveryBlock)
    assert eb.label == "blinker"
    assert eb.interval == 2000
    assert eb.offset_ms == 200

def test_config_scheduler_slots():
    prog = parse("@config scheduler_slots = 32;")
    cfg = prog.body[0]
    assert isinstance(cfg, SchedulerConfig)
    assert cfg.key == "scheduler_slots"
    assert cfg.value == 32

def test_after_block_in_statement_position():
    """after blocks should work inside other blocks"""
    prog = parse("tick { after 500ms { print(\"x\"); } }")
    tick = prog.body[0]
    assert isinstance(tick, TickBlock)
    assert isinstance(tick.body[0], AfterBlock)
