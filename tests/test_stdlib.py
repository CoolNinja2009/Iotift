"""
Standard library tests — verifies each stdlib module can be imported and
generates correct C code through the full pipeline.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from lexer import tokenize
from parser import Parser
from semantic import SemanticAnalyzer
from codegen import CodeGen
from import_resolver import ImportResolver


# ── helpers ─────────────────────────────────────────────────────

STDLIB_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'iotift', 'stdlib',
)


def resolve_stdlib(main_source):
    """Resolve imports using the REAL stdlib directory."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        main_path = os.path.join(tmpdir, 'main.iot')
        with open(main_path, 'w', encoding='utf-8') as f:
            f.write(main_source)

        with open(main_path, encoding='utf-8') as f:
            tokens = tokenize(f.read())
        ast = Parser(tokens).parse()

        resolver = ImportResolver()
        # Point to real stdlib
        resolver._find_stdlib = lambda fp: STDLIB_DIR
        ast = resolver.resolve(ast, main_path)

        sa = SemanticAnalyzer()
        sa.analyze(ast)
        return sa, ast


def compile_stdlib(main_source):
    """Full pipeline including real stdlib import resolution."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        main_path = os.path.join(tmpdir, 'main.iot')
        with open(main_path, 'w', encoding='utf-8') as f:
            f.write(main_source)

        with open(main_path, encoding='utf-8') as f:
            tokens = tokenize(f.read())
        ast = Parser(tokens).parse()

        resolver = ImportResolver()
        resolver._find_stdlib = lambda fp: STDLIB_DIR
        ast = resolver.resolve(ast, main_path)

        sa = SemanticAnalyzer()
        sa.analyze(ast)
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"

        gen = CodeGen()
        return gen.generate(ast)


# ════════════════════════════════════════════════════════════════
#  PRELUDE TESTS (time, math, gpio auto-imported)
# ════════════════════════════════════════════════════════════════

class TestPrelude:
    """Prelude modules (time, math, gpio) are auto-imported."""

    def test_time_prelude_available(self):
        """millis() should be available without explicit import."""
        sa, ast = resolve_stdlib(
            'pin LED = output 2;\n'
            'every 500 { int t = millis(); }\n'
        )
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"

    def test_math_prelude_available(self):
        """sin() etc. should resolve from prelude."""
        # Note: sin() produces MathExpr, which is handled specially.
        # The prelude still registers the symbol for name resolution.
        sa, ast = resolve_stdlib(
            'pin LED = output 2;\n'
            'every 500 { float x = sin(0.5); }\n'
        )
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"

    def test_gpio_prelude_available(self):
        """digitalWrite() etc. should be available without explicit import."""
        sa, ast = resolve_stdlib(
            'pin LED = output 2;\n'
            'every 500 { digitalWrite(2, 1); }\n'
        )
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"

    def test_delay_available(self):
        """delay() should be available from time prelude."""
        sa, ast = resolve_stdlib(
            'pin LED = output 2;\n'
            'every 500 { delay(100); }\n'
        )
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"

    def test_micros_available(self):
        """micros() should be available from time prelude."""
        sa, ast = resolve_stdlib(
            'pin LED = output 2;\n'
            'every 500 { int t = micros(); }\n'
        )
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"


# ════════════════════════════════════════════════════════════════
#  MATH STDLIB TESTS
# ════════════════════════════════════════════════════════════════

class TestMathStdlib:
    """Math stdlib functions generate correct C code."""

    def test_math_import_includes_math_header(self):
        """math.h is included only when math functions are actually used."""
        c = compile_stdlib(
            'import "math";\n'
            'pin LED = output 2;\n'
            'every 500 { float x = sin(0.5); }\n'
        )
        assert '#include <math.h>' in c

    def test_math_header_from_prelude(self):
        """Prelude math should include math.h when math is called."""
        c = compile_stdlib(
            'pin LED = output 2;\n'
            'every 500 { float x = sin(0.5); }\n'
        )
        assert '#include <math.h>' in c

    def test_sin_cos_tan(self):
        sa, ast = resolve_stdlib(
            'pin LED = output 2;\n'
            'every 500 { float a = sin(0.5); float b = cos(0.5); float c = tan(0.5); }\n'
        )
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"

    def test_sqrt_abs_pow(self):
        sa, ast = resolve_stdlib(
            'pin LED = output 2;\n'
            'every 500 { float a = sqrt(2.0); float b = abs(-5.0); float c = pow(2.0, 3.0); }\n'
        )
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"

    def test_floor_ceil_round(self):
        sa, ast = resolve_stdlib(
            'pin LED = output 2;\n'
            'every 500 { float a = floor(2.7); float b = ceil(2.3); float c = round(2.5); }\n'
        )
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"

    def test_log_exp(self):
        sa, ast = resolve_stdlib(
            'pin LED = output 2;\n'
            'every 500 { float a = log(2.0); float b = exp(1.0); }\n'
        )
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"


# ════════════════════════════════════════════════════════════════
#  EXPLICIT STDLIB IMPORT TESTS
# ════════════════════════════════════════════════════════════════

class TestExplicitStdlibImports:
    """Explicitly importing stdlib modules."""

    def test_explicit_serial_import(self):
        sa, ast = resolve_stdlib(
            'import "serial";\n'
            'every 500 { serialBegin(115200); }\n'
        )
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"

    def test_explicit_i2c_import(self):
        sa, ast = resolve_stdlib(
            'import "i2c";\n'
            'every 500 { i2cBegin(); }\n'
        )
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"

    def test_explicit_spi_import(self):
        sa, ast = resolve_stdlib(
            'import "spi";\n'
            'every 500 { spiBegin(); }\n'
        )
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"

    def test_explicit_pwm_import(self):
        sa, ast = resolve_stdlib(
            'import "pwm";\n'
            'every 500 { pwmSetup(0, 5000, 8); }\n'
        )
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"


# ════════════════════════════════════════════════════════════════
#  FULL CODEGEN TESTS
# ════════════════════════════════════════════════════════════════

class TestStdlibCodegen:
    """Verify stdlib function calls generate correct C code."""

    def test_millis_codegen(self):
        c = compile_stdlib(
            'pin LED = output 2;\n'
            'every 500 { int t = millis(); }\n'
        )
        assert 'millis()' in c

    def test_delay_codegen(self):
        c = compile_stdlib(
            'pin LED = output 2;\n'
            'every 500 { delay(100); }\n'
        )
        assert 'delay(100)' in c

    def test_digitalwrite_codegen(self):
        c = compile_stdlib(
            'pin LED = output 2;\n'
            'every 500 { digitalWrite(2, 1); }\n'
        )
        assert 'digitalWrite(2, 1)' in c

    def test_serial_begin_codegen(self):
        c = compile_stdlib(
            'import "serial";\n'
            'pin LED = output 2;\n'
            'every 500 { serialBegin(9600); }\n'
        )
        assert '9600' in c  # baud rate appears in generated code
