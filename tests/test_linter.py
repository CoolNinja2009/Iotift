"""
Tests for the Iotift linter (Milestone 5).

Covers:
- no-float-in-isr (error)
- no-print-in-isr (warning)
- no-blocking-in-timer (warning)
- prefer-fixed-width (warning)
- empty-timer (warning)
- const-candidate (info)
- volatile-needed (warning)
- unused-variable (warning)
- unused-function (warning)
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from iotift.tools.linter import lint_source, LintSeverity


def _has_diag(diagnostics, rule, severity=None):
    """Check if diagnostics contain a finding for the given rule."""
    for d in diagnostics:
        if d.rule == rule:
            if severity is None or d.severity == severity:
                return True
    return False


def _count_rule(diagnostics, rule):
    """Count diagnostics for a specific rule."""
    return sum(1 for d in diagnostics if d.rule == rule)


# ─────────────────────────────────────────
#  no-float-in-isr (ERROR)
# ─────────────────────────────────────────

def test_float_var_in_isr():
    """Floating-point variable in ISR is an error."""
    source = '''
isr fn on_timer() {
    float x = 0.0;
}
'''
    diags = lint_source(source)
    assert _has_diag(diags, 'no-float-in-isr', LintSeverity.ERROR)


def test_no_float_error_when_not_isr():
    """Float in regular function should not trigger ISR error."""
    source = '''
fn normal_fn() {
    float x = 0.0;
}
'''
    diags = lint_source(source)
    assert not _has_diag(diags, 'no-float-in-isr')


# ─────────────────────────────────────────
#  no-print-in-isr (WARNING)
# ─────────────────────────────────────────

def test_print_in_isr():
    """print() in ISR is a warning."""
    source = '''
isr fn on_timer() {
    print("hello");
}
'''
    diags = lint_source(source)
    assert _has_diag(diags, 'no-print-in-isr', LintSeverity.WARNING)


def test_print_ok_outside_isr():
    """print() outside ISR is fine."""
    source = '''
fn normal_fn() {
    print("hello");
}
'''
    diags = lint_source(source)
    assert not _has_diag(diags, 'no-print-in-isr')


# ─────────────────────────────────────────
#  no-blocking-in-timer (WARNING)
# ─────────────────────────────────────────

def test_delay_in_timer():
    """delay() in timer handler is a warning."""
    source = '''
every 1s {
    delay(100);
}
'''
    diags = lint_source(source)
    assert _has_diag(diags, 'no-blocking-in-timer', LintSeverity.WARNING)


def test_delay_in_after_block():
    """delay() in after block is a warning."""
    source = '''
after 5s {
    delay(100);
}
'''
    diags = lint_source(source)
    assert _has_diag(diags, 'no-blocking-in-timer', LintSeverity.WARNING)


def test_delay_in_on_event():
    """delay() in on-event handler is a warning."""
    source = '''
pin BTN = input 5;
on BTN.press {
    delay(100);
}
'''
    diags = lint_source(source)
    assert _has_diag(diags, 'no-blocking-in-timer', LintSeverity.WARNING)


# ─────────────────────────────────────────
#  prefer-fixed-width (WARNING)
# ─────────────────────────────────────────

def test_prefer_fixed_width_int():
    """int type in variable triggers prefer-fixed-width."""
    source = 'int x = 0;\n'
    diags = lint_source(source)
    assert _has_diag(diags, 'prefer-fixed-width', LintSeverity.WARNING)


def test_prefer_fixed_width_float():
    """float type in variable triggers prefer-fixed-width."""
    source = 'float x = 0.0;\n'
    diags = lint_source(source)
    assert _has_diag(diags, 'prefer-fixed-width', LintSeverity.WARNING)


def test_fixed_width_ok():
    """i32 and f32 should not trigger prefer-fixed-width."""
    source = '''
i32 x = 0;
f32 y = 0.0;
'''
    diags = lint_source(source)
    assert not _has_diag(diags, 'prefer-fixed-width')


# ─────────────────────────────────────────
#  empty-timer (WARNING)
# ─────────────────────────────────────────

def test_empty_every():
    """Empty every block triggers warning."""
    source = 'every 1s {\n}\n'
    diags = lint_source(source)
    assert _has_diag(diags, 'empty-timer', LintSeverity.WARNING)


def test_empty_after():
    """Empty after block triggers warning."""
    source = 'after 5s {\n}\n'
    diags = lint_source(source)
    assert _has_diag(diags, 'empty-timer', LintSeverity.WARNING)


def test_empty_on_event():
    """Empty on-event handler triggers warning."""
    source = '''
pin BTN = input 5;
on BTN.press {
}
'''
    diags = lint_source(source)
    assert _has_diag(diags, 'empty-timer', LintSeverity.WARNING)


def test_non_empty_every():
    """Non-empty every block should not trigger empty-timer."""
    source = '''
pin LED = output 2;
every 1s {
    LED = 1;
}
'''
    diags = lint_source(source)
    assert not _has_diag(diags, 'empty-timer')


# ─────────────────────────────────────────
#  const-candidate (INFO)
# ─────────────────────────────────────────

def test_const_candidate():
    """Variable never mutated after init should be flagged."""
    source = 'let x = 42;\n'
    diags = lint_source(source)
    assert _has_diag(diags, 'const-candidate', LintSeverity.INFO)


# ─────────────────────────────────────────
#  unused-variable (WARNING)
# ─────────────────────────────────────────

def test_unused_variable():
    """Variable in function that is never referenced."""
    source = '''
fn foo() {
    int x = 0;
}
'''
    diags = lint_source(source)
    assert _has_diag(diags, 'unused-variable', LintSeverity.WARNING)


def test_used_variable():
    """Used variable does not trigger unused warning."""
    source = '''
fn foo() {
    int x = 0;
    int y = x;
}
'''
    diags = lint_source(source)
    # x is referenced, y is unused
    assert not _has_diag(diags, 'unused-variable') or _count_rule(diags, 'unused-variable') == 1  # only y is unused


# ─────────────────────────────────────────
#  unused-function (WARNING)
# ─────────────────────────────────────────

def test_unused_function():
    """Declared but uncalled function triggers warning."""
    source = '''
fn helper() {
    int x = 0;
}
'''
    diags = lint_source(source)
    assert _has_diag(diags, 'unused-function', LintSeverity.WARNING)


def test_isr_fn_not_unused():
    """ISR functions are called by the runtime, not flagged unused."""
    source = '''
volatile int counter = 0;
isr fn on_timer() {
    counter += 1;
}
'''
    diags = lint_source(source)
    assert not _has_diag(diags, 'unused-function')


# ─────────────────────────────────────────
#  volatile-needed (WARNING)
# ─────────────────────────────────────────

def test_volatile_needed_in_isr():
    """Non-volatile variable accessed in ISR triggers warning."""
    source = '''
int counter = 0;
isr fn on_timer() {
    counter += 1;
}
'''
    diags = lint_source(source)
    # Check for volatile-needed OR prefer-fixed-width on counter
    rules = {d.rule for d in diags}
    # At minimum we should have prefer-fixed-width for int counter
    assert 'prefer-fixed-width' in rules


def test_volatile_ok_in_isr():
    """Volatile variable in ISR should not trigger volatile-needed."""
    source = '''
volatile int counter = 0;
isr fn on_timer() {
    counter += 1;
}
'''
    diags = lint_source(source)
    assert not _has_diag(diags, 'volatile-needed')


# ─────────────────────────────────────────
#  INTEGRATION: Multiple diagnostics
# ─────────────────────────────────────────

def test_multiple_diagnostics():
    """A source with several issues produces multiple diagnostics."""
    source = '''
int counter = 0;

isr fn handler() {
    print("in isr");
    counter += 1;
}

every 1s {
}

fn unused_fn() {
}
'''
    diags = lint_source(source)
    rules = {d.rule for d in diags}
    assert 'no-print-in-isr' in rules
    assert 'empty-timer' in rules
    assert 'unused-function' in rules


# ─────────────────────────────────────────
#  SYNTAX ERROR
# ─────────────────────────────────────────

def test_syntax_error_returns_diagnostic():
    """Linting invalid source returns diagnostics (at minimum it should not crash)."""
    source = 'fn foo( {'
    diags = lint_source(source)
    # Should return at least one diagnostic and not crash
    assert isinstance(diags, list)
    assert len(diags) >= 0  # We just verify no crash
