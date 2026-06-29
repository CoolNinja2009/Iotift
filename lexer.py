"""
IOTIFT Lexer — Production Rewrite

Tokenises raw source text into a flat list of Token objects.
Improved: hex/bin/oct literals, char literals, escape sequences,
fixed-width type keywords, new language keywords, better performance.
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from typing import List, Dict, Optional


# ─────────────────────────────────────────
#  TOKEN TYPES
# ─────────────────────────────────────────

class TT:
    """Token-type constants — one attribute per terminal symbol."""

    # ── literals ──
    INT_LIT    = 'INT_LIT'       # integer (dec, hex, bin, oct)
    FLOAT_LIT  = 'FLOAT_LIT'     # float
    STR_LIT    = 'STR_LIT'       # string "..."
    CHAR_LIT   = 'CHAR_LIT'      # character 'x'
    BOOL_LIT   = 'BOOL_LIT'      # true | false

    # ── identifiers ──
    IDENT      = 'IDENT'         # user identifier
    KEYWORD    = 'KEYWORD'       # language keyword
    TYPE_KW    = 'TYPE_KW'       # built-in type keyword (distinct for parser)

    # ── operators ──
    OP         = 'OP'            # + - * / % ! ~ & | ^ << >> += -= ...

    # ── punctuation ──
    LPAREN     = 'LPAREN'       # (
    RPAREN     = 'RPAREN'       # )
    LBRACE     = 'LBRACE'       # {
    RBRACE     = 'RBRACE'       # }
    LBRACKET   = 'LBRACKET'     # [
    RBRACKET   = 'RBRACKET'     # ]
    SEMICOLON  = 'SEMICOLON'    # ;
    C_BLOCK    = 'C_BLOCK'      # c header/global/setup/loop { ... }
    COMMA      = 'COMMA'        # ,
    DOT        = 'DOT'          # .
    DOTDOT     = 'DOTDOT'       # ..
    DOTDOTEQ   = 'DOTDOTEQ'     # ..=
    ARROW      = 'ARROW'        # ->
    FAT_ARROW  = 'FAT_ARROW'    # =>
    AT         = 'AT'           # @
    COLON      = 'COLON'        # :
    COLONCOLON = 'COLONCOLON'   # ::
    QUESTION   = 'QUESTION'     # ?
    HASH       = 'HASH'         # #

    # ── special ──
    EOF        = 'EOF'


# ─────────────────────────────────────────
#  KEYWORD SETS
# ─────────────────────────────────────────

# Language keywords that control flow and declarations.
KEYWORDS = frozenset({
    # Control flow
    'if', 'else', 'while', 'for', 'loop', 'break', 'continue',
    'return', 'defer',
    # Declarations
    'let', 'var', 'const', 'fn', 'struct', 'enum',
    'extern', 'type',
    # Embedded
    'pin', 'on', 'every', 'schedule', 'tick',
    'stop', 'as', 'after', 'isr', 'volatile',
    # Values
    'true', 'false',
    # Pin directions (contextual keywords — treated as IDENT then resolved)
    'output', 'input', 'analog', 'i2c', 'spi', 'pwm',
    # Peripherals
    'uart', 'adc', 'dac',
    # Pin events (contextual — both intuitive and technical names coexist)
    'rising', 'falling', 'change', 'press', 'release',
    # Other
    'import', 'from', 'print', 'println', 'sizeof',
    # Scheduler / timer extensions
    'offset', 'config',
})

# Built-in type names — get TYPE_KW token type.
TYPE_KEYWORDS = frozenset({
    # Platform-width
    'int', 'uint', 'float', 'bool', 'str', 'char', 'void',
    # Fixed-width signed
    'i8', 'i16', 'i32', 'i64',
    # Fixed-width unsigned
    'u8', 'u16', 'u32', 'u64',
    # Fixed-width float
    'f32', 'f64',
})

# Time-suffix to millisecond multiplier.
_TIME_SUFFIX_MS: Dict[str, int] = {'ms': 1, 's': 1000, 'm': 60000, 'h': 3600000}


# ─────────────────────────────────────────
#  TOKEN
# ─────────────────────────────────────────

@dataclass
class Token:
    type: str
    value: object                   # str | int | float | bool | tuple | None
    line: int
    col: int
    end_col: int = 0                # column after token

    def __repr__(self) -> str:
        return f"Token({self.type}, {self.value!r}, {self.line}:{self.col})"


# ─────────────────────────────────────────
#  LEXER
# ─────────────────────────────────────────

class LexError(Exception):
    """Raised when the lexer encounters an unexpected character."""
    def __init__(self, message: str, line: int, col: int):
        super().__init__(f"Line {line} col {col}: {message}")
        self.line = line
        self.col = col


# Ordered patterns — first match wins.
# Float before int to handle "123.456".
# DotDot before Dot to handle "..".
_TOKEN_PATTERNS: List[tuple] = [
    ('SKIP',       re.compile(r'[ \t\r]+')),
    ('COMMENT',    re.compile(r'//[^\n]*')),
    ('NEWLINE',    re.compile(r'\n')),
    # Float: digits.digits with optional exponent
    ('FLOAT_LIT',  re.compile(r'\d+\.\d+([eE][+-]?\d+)?')),
    # Time literals: digits followed by time suffix
    ('TIME_LIT',   re.compile(r'\d+(ms|[smh])\b')),
    # Hex: 0x...
    ('INT_LIT_HEX', re.compile(r'0[xX][0-9a-fA-F_]+')),
    # Binary: 0b...
    ('INT_LIT_BIN', re.compile(r'0[bB][01_]+')),
    # Octal: 0o...
    ('INT_LIT_OCT', re.compile(r'0[oO][0-7_]+')),
    # Decimal integer
    ('INT_LIT',    re.compile(r'\d[\d_]*')),
    # Character literal: 'x' with escapes (including \xNN hex)
    ('CHAR_LIT',   re.compile(r"'(?:\\x[0-9a-fA-F]{2}|\\[0-7]{1,3}|\\.|[^'\\])'")),
    # String literal with escapes
    ('STR_LIT',    re.compile(r'"(?:\\.|[^"\\])*"')),
    # Multi-char operators (longest match first)
    ('DOTDOTEQ',   re.compile(r'\.\.=')),
    ('DOTDOT',     re.compile(r'\.\.')),
    ('FAT_ARROW',  re.compile(r'=>')),
    ('ARROW',      re.compile(r'->')),
    ('COLONCOLON', re.compile(r'::')),
    # Compound assignment & comparison ops
    ('OP',         re.compile(r'<<=|>>=|&&|\|\||==|!=|<=|>=|'
                              r'\+=|-=|\*=|/=|%=|&=|\|=|\^=|<<|>>|'
                              r'[+\-*/%!<>=&|^~?]')),
    # Punctuation
    ('LPAREN',     re.compile(r'\(')),
    ('RPAREN',     re.compile(r'\)')),
    ('LBRACE',     re.compile(r'\{')),
    ('RBRACE',     re.compile(r'\}')),
    ('LBRACKET',   re.compile(r'\[')),
    ('RBRACKET',   re.compile(r'\]')),
    ('SEMICOLON',  re.compile(r';')),
    ('COMMA',      re.compile(r',')),
    ('DOT',        re.compile(r'\.')),
    ('AT',         re.compile(r'@')),
    ('COLON',      re.compile(r':')),
    ('HASH',       re.compile(r'#')),
    ('IDENT',      re.compile(r'[A-Za-z_]\w*')),
]


def _parse_string_escapes(raw: str, line: int, col: int) -> str:
    """Process C-style escape sequences in a string literal."""
    result = []
    i = 0
    s = raw[1:-1]  # strip quotes
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s):
            c = s[i + 1]
            esc = {
                'n': '\n', 't': '\t', 'r': '\r', '\\': '\\',
                '"': '"', "'": "'", '0': '\0',
                'x': None,  # hex escape handled below
            }
            if c == 'x' and i + 3 < len(s):
                try:
                    result.append(chr(int(s[i+2:i+4], 16)))
                    i += 4
                    continue
                except (ValueError, IndexError):
                    raise LexError(f"Invalid hex escape in string", line, col)
            if c in esc:
                result.append(esc[c])
                i += 2
            else:
                result.append(s[i+1])
                i += 2
        else:
            result.append(s[i])
            i += 1
    return ''.join(result)


def _parse_char_literal(raw: str, line: int, col: int) -> str:
    """Process escape sequences in a character literal. Returns single char."""
    inner = raw[1:-1]  # strip quotes
    if len(inner) == 1 and inner[0] != '\\':
        return inner
    if inner.startswith('\\'):
        c = inner[1] if len(inner) > 1 else '\\'
        esc = {'n': '\n', 't': '\t', 'r': '\r', '\\': '\\',
               "'": "'", '"': '"', '0': '\0'}
        if c == 'x' and len(inner) >= 4:
            try:
                return chr(int(inner[2:4], 16))
            except ValueError:
                raise LexError(f"Invalid hex escape in char literal", line, col)
        return esc.get(c, c)
    raise LexError(f"Invalid character literal {raw}", line, col)


def _parse_int(raw: str, base: int = 10) -> int:
    """Parse an integer literal, stripping underscores."""
    cleaned = raw.replace('_', '')
    if base == 16:
        cleaned = cleaned[2:]  # strip 0x
    elif base == 2:
        cleaned = cleaned[2:]  # strip 0b
    elif base == 8:
        cleaned = cleaned[2:]  # strip 0o
    return int(cleaned, base)


def _is_word_boundary(source: str, pos: int) -> bool:
    """True when pos is at/past end of source, or char is not ident continuation."""
    return pos >= len(source) or not (source[pos].isalnum() or source[pos] == '_')


def tokenize(source: str) -> List[Token]:
    """Convert raw Iotift source text into a flat list of Token objects."""

    tokens: List[Token] = []
    pos: int = 0
    line: int = 1
    line_start: int = 0

    while pos < len(source):
        # ── raw C injection blocks ──────────────────────────
        if source[pos] == 'c' and _is_word_boundary(source, pos + 1):
            m = re.match(r'c\b\s+(header|global|setup|loop|isr)\b\s*', source[pos:])
            if m:
                brace_pos = pos + len(m.group(0))
                if brace_pos < len(source) and source[brace_pos] == '{':
                    start_line = line
                    start_col  = pos - line_start + 1
                    scope      = m.group(1)
                    scan_pos   = brace_pos
                    depth      = 0
                    scan_line  = line
                    scan_line_start = line_start

                    while scan_pos < len(source):
                        ch = source[scan_pos]
                        if ch == '{':
                            depth += 1
                            scan_pos += 1
                        elif ch == '}':
                            depth -= 1
                            scan_pos += 1
                            if depth == 0:
                                break
                        elif ch in ('"', "'"):
                            quote = ch
                            scan_pos += 1
                            while scan_pos < len(source):
                                if source[scan_pos] == '\\':
                                    scan_pos += 2
                                elif source[scan_pos] == quote:
                                    scan_pos += 1
                                    break
                                else:
                                    if source[scan_pos] == '\n':
                                        scan_line += 1
                                        scan_line_start = scan_pos + 1
                                    scan_pos += 1
                        elif source[scan_pos:scan_pos + 2] == '//':
                            scan_pos += 2
                            while scan_pos < len(source) and source[scan_pos] != '\n':
                                scan_pos += 1
                        elif source[scan_pos:scan_pos + 2] == '/*':
                            scan_pos += 2
                            while (scan_pos + 1 < len(source)
                                   and source[scan_pos:scan_pos + 2] != '*/'):
                                if source[scan_pos] == '\n':
                                    scan_line += 1
                                    scan_line_start = scan_pos + 1
                                scan_pos += 1
                            scan_pos += 2 if scan_pos + 1 < len(source) else 1
                        elif source[scan_pos] == '\n':
                            scan_line += 1
                            scan_line_start = scan_pos + 1
                            scan_pos += 1
                        else:
                            scan_pos += 1

                    if depth != 0:
                        raise LexError(
                            f"Unterminated C block starting at line {start_line} col {start_col}",
                            start_line, start_col
                        )

                    raw_code = source[brace_pos + 1 : scan_pos - 1]
                    raw_code = '\n'.join(
                        ln.rstrip() for ln in raw_code.splitlines() if ln.strip()
                    )
                    tokens.append(
                        Token(TT.C_BLOCK, (scope, raw_code), start_line, start_col,
                              end_col=scan_pos - line_start)
                    )
                    pos        = scan_pos
                    line       = scan_line
                    line_start = scan_line_start
                    continue

        # ── block comments  /* ... */  (state machine, avoids ReDoS) ──
        if source[pos:pos + 2] == '/*':
            scan_pos = pos + 2
            while scan_pos < len(source):
                if source[scan_pos] == '\n':
                    line += 1
                    line_start = scan_pos + 1
                    scan_pos += 1
                elif source[scan_pos:scan_pos + 2] == '*/':
                    scan_pos += 2
                    break
                else:
                    scan_pos += 1
            else:
                # Unterminated block comment
                raise LexError(
                    f"Unterminated block comment starting at line {line} col {pos - line_start + 1}",
                    line, pos - line_start + 1
                )
            pos = scan_pos
            continue

        # ── normal token patterns ──────────────────────────
        matched = False
        for ttype, pat in _TOKEN_PATTERNS:
            m = pat.match(source, pos)
            if not m:
                continue

            col  = pos - line_start + 1
            text = m.group(0)
            end_col = col + len(text)

            if ttype in ('SKIP', 'COMMENT'):
                pass   # discard

            elif ttype == 'NEWLINE':
                line       += 1
                line_start  = pos + 1

            elif ttype == 'FLOAT_LIT':
                tokens.append(Token(TT.FLOAT_LIT, float(text), line, col, end_col))

            elif ttype == 'TIME_LIT':
                # Parse "500ms", "2s", "5m", "1h"
                suffix_len = 2 if text[-2:] == 'ms' else 1
                suffix = text[-suffix_len:]
                num_str = text[:-suffix_len].replace('_', '')
                ms = int(num_str) * _TIME_SUFFIX_MS[suffix]
                tokens.append(Token(TT.INT_LIT, ms, line, col, end_col))

            elif ttype == 'INT_LIT_HEX':
                val = _parse_int(text, base=16)
                tokens.append(Token(TT.INT_LIT, val, line, col, end_col))

            elif ttype == 'INT_LIT_BIN':
                val = _parse_int(text, base=2)
                tokens.append(Token(TT.INT_LIT, val, line, col, end_col))

            elif ttype == 'INT_LIT_OCT':
                val = _parse_int(text, base=8)
                tokens.append(Token(TT.INT_LIT, val, line, col, end_col))

            elif ttype == 'INT_LIT':
                val = _parse_int(text, base=10)
                tokens.append(Token(TT.INT_LIT, val, line, col, end_col))

            elif ttype == 'STR_LIT':
                try:
                    escaped = _parse_string_escapes(text, line, col)
                except LexError:
                    escaped = text[1:-1]  # fallback: raw content
                tokens.append(Token(TT.STR_LIT, escaped, line, col, end_col))

            elif ttype == 'CHAR_LIT':
                try:
                    ch = _parse_char_literal(text, line, col)
                except LexError:
                    ch = text[1:-1] if len(text) >= 3 else text
                tokens.append(Token(TT.CHAR_LIT, ch, line, col, end_col))

            elif ttype == 'IDENT':
                if text in ('true', 'false'):
                    tokens.append(Token(TT.BOOL_LIT, text == 'true', line, col, end_col))
                elif text in TYPE_KEYWORDS:
                    tokens.append(Token(TT.TYPE_KW, text, line, col, end_col))
                elif text in KEYWORDS:
                    tokens.append(Token(TT.KEYWORD, text, line, col, end_col))
                else:
                    tokens.append(Token(TT.IDENT, text, line, col, end_col))

            elif ttype == 'OP':
                # Filter out stray '?' not part of '?' operator
                tokens.append(Token(TT.OP, text, line, col, end_col))

            else:
                tokens.append(Token(ttype, text, line, col, end_col))

            pos    += len(text)
            matched = True
            break

        if not matched:
            raise LexError(
                f"Unexpected character {source[pos]!r}",
                line, pos - line_start + 1
            )

    tokens.append(Token(TT.EOF, None, line, 0, 0))
    return tokens
