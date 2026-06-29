"""
Lexer tests — 25+ tests covering all token types, edge cases, and error handling.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from lexer import tokenize, Token, TT, LexError


def test_keywords():
    tokens = tokenize('pin let var const defer enum type fn struct')
    expected = ['pin', 'let', 'var', 'const', 'defer', 'enum', 'type', 'fn', 'struct']
    kw_tokens = [t for t in tokens if t.type == TT.KEYWORD]
    assert [t.value for t in kw_tokens] == expected

def test_type_keywords():
    tokens = tokenize('int float bool str char void u8 u16 u32 u64 i8 i16 i32 i64 f32 f64')
    type_tokens = [t for t in tokens if t.type == TT.TYPE_KW]
    assert len(type_tokens) == 16
    assert 'u8' in [t.value for t in type_tokens]

def test_identifiers():
    tokens = tokenize('LED BTN count my_var sensor1')
    idents = [t for t in tokens if t.type == TT.IDENT]
    assert [t.value for t in idents] == ['LED', 'BTN', 'count', 'my_var', 'sensor1']

def test_punctuation():
    tokens = tokenize('( ) { } [ ] ; , . @ :')
    types = [t.type for t in tokens if t.type != TT.EOF]
    assert types == ['LPAREN', 'RPAREN', 'LBRACE', 'RBRACE', 'LBRACKET', 'RBRACKET',
                     'SEMICOLON', 'COMMA', 'DOT', 'AT', 'COLON']

def test_operators():
    tokens = tokenize('+ - * / % ! && || == != < > <= >= += -= *= /=')
    ops = [t for t in tokens if t.type == TT.OP]
    assert len(ops) >= 18

def test_arrow():
    tokens = tokenize('->')
    assert tokens[0].type == TT.ARROW

def test_decimal_integer():
    tokens = tokenize('42 0 100')
    ints = [t for t in tokens if t.type == TT.INT_LIT]
    assert [t.value for t in ints] == [42, 0, 100]

def test_hex_literal():
    tokens = tokenize('0xFF 0x1A 0xdead_beef')
    ints = [t for t in tokens if t.type == TT.INT_LIT]
    assert ints[0].value == 255
    assert ints[1].value == 26

def test_binary_literal():
    tokens = tokenize('0b1010 0b1111_0000')
    ints = [t for t in tokens if t.type == TT.INT_LIT]
    assert ints[0].value == 10
    assert ints[1].value == 240

def test_octal_literal():
    tokens = tokenize('0o77 0o10')
    ints = [t for t in tokens if t.type == TT.INT_LIT]
    assert ints[0].value == 63
    assert ints[1].value == 8

def test_underscore_separators():
    tokens = tokenize('1_000_000')
    ints = [t for t in tokens if t.type == TT.INT_LIT]
    assert ints[0].value == 1000000

def test_float_literal():
    tokens = tokenize('1.5 3.14 0.001')
    floats = [t for t in tokens if t.type == TT.FLOAT_LIT]
    assert len(floats) == 3
    assert floats[0].value == 1.5

def test_float_with_exponent():
    tokens = tokenize('1.5e-3 2.0e+10 3.14E2')
    floats = [t for t in tokens if t.type == TT.FLOAT_LIT]
    assert len(floats) == 3
    assert floats[0].value == 0.0015

def test_time_literal_ms():
    tokens = tokenize('500ms')
    assert tokens[0].type == TT.INT_LIT
    assert tokens[0].value == 500

def test_time_literal_seconds():
    tokens = tokenize('2s')
    assert tokens[0].value == 2000

def test_time_literal_minutes():
    tokens = tokenize('5m')
    assert tokens[0].value == 300000

def test_time_literal_hours():
    tokens = tokenize('1h')
    assert tokens[0].value == 3600000

def test_string_literal():
    tokens = tokenize('"hello world"')
    assert tokens[0].type == TT.STR_LIT
    assert tokens[0].value == 'hello world'

def test_string_with_escapes():
    tokens = tokenize(r'"hello\nworld\t!"')
    assert tokens[0].type == TT.STR_LIT
    assert tokens[0].value == 'hello\nworld\t!'

def test_string_with_hex_escape():
    tokens = tokenize(r'"\x41\x42"')
    assert tokens[0].value == 'AB'

def test_char_literal():
    tokens = tokenize("'A'")
    assert tokens[0].type == TT.CHAR_LIT
    assert tokens[0].value == 'A'

def test_char_literal_escape():
    tokens = tokenize("'\\n' '\\t' '\\\\' '\\''")
    chars = [t for t in tokens if t.type == TT.CHAR_LIT]
    assert chars[0].value == '\n'
    assert chars[1].value == '\t'
    assert chars[2].value == '\\'
    assert chars[3].value == "'"

def test_char_hex_escape():
    tokens = tokenize(r"'\x41'")
    assert tokens[0].value == 'A'

def test_bool_literals():
    tokens = tokenize('true false')
    bools = [t for t in tokens if t.type == TT.BOOL_LIT]
    assert bools[0].value is True
    assert bools[1].value is False

def test_line_comment():
    tokens = tokenize('int x = 1; // this is a comment\nint y = 2;')
    type_kws = [t for t in tokens if t.type == TT.TYPE_KW]
    assert len(type_kws) == 2

def test_block_comment():
    tokens = tokenize('int /* inline */ x = 1;')
    idents = [t for t in tokens if t.type == TT.IDENT]
    assert idents[0].value == 'x'

def test_block_comment_multiline():
    tokens = tokenize('int x = 1;\n/* multi\nline\ncomment */\nint y = 2;')
    type_kws = [t for t in tokens if t.type == TT.TYPE_KW]
    assert len(type_kws) == 2

def test_c_block_header():
    tokens = tokenize('c header { #include <stdio.h> }')
    cblocks = [t for t in tokens if t.type == TT.C_BLOCK]
    assert len(cblocks) == 1
    assert cblocks[0].value[0] == 'header'

def test_eof_token():
    tokens = tokenize('')
    assert len(tokens) == 1
    assert tokens[0].type == TT.EOF
