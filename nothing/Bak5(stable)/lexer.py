"""
IOTIFT Lexer
Turns raw source text into a flat list of tokens.
"""

import re
from dataclasses import dataclass
from typing import Optional

# ─────────────────────────────────────────
#  TOKEN TYPES
# ─────────────────────────────────────────

TT = type('TT', (), {
    # literals
    'INT_LIT'    : 'INT_LIT',
    'FLOAT_LIT'  : 'FLOAT_LIT',
    'STR_LIT'    : 'STR_LIT',
    'BOOL_LIT'   : 'BOOL_LIT',

    # identifiers & keywords
    'IDENT'      : 'IDENT',
    'KEYWORD'    : 'KEYWORD',

    # operators
    'OP'         : 'OP',       # + - * / % ! += -= == != < > <= >= = && ||

    # punctuation
    'LPAREN'     : 'LPAREN',   # (
    'RPAREN'     : 'RPAREN',   # )
    'LBRACE'     : 'LBRACE',   # {
    'RBRACE'     : 'RBRACE',   # }
    'LBRACKET'   : 'LBRACKET', # [
    'RBRACKET'   : 'RBRACKET', # ]
    'SEMICOLON'  : 'SEMICOLON',# ;
    'C_BLOCK'    : 'C_BLOCK',  # c { ... }
    'C_HEADER'   : 'C_HEADER', # c header { ... }
    'COMMA'      : 'COMMA',    # ,
    'DOT'        : 'DOT',      # .
    'ARROW'      : 'ARROW',    # ->
    'AT'         : 'AT',       # @
    'COLON'      : 'COLON',    # :

    # special
    'EOF'        : 'EOF',
    'NEWLINE'    : 'NEWLINE',
})()

KEYWORDS = {
    'pin', 'int', 'float', 'bool', 'str', 'const', 'struct',
    'fn', 'extern', 'return', 'void',
    'if', 'else', 'while', 'for', 'loop', 'break', 'continue',
    'on', 'every', 'after', 'as', 'stop',
    'import', 'print', 'millis',
    'true', 'false',
    'input', 'output', 'analog', 'i2c', 'spi', 'pwm',
    'read', 'write',
    'device',
}

TIME_SUFFIX = {'s': 1000, 'm': 60000}   # s → ×1000 ms, m → ×60000 ms


@dataclass
class Token:
    type  : str
    value : object          # str / int / float / bool
    line  : int
    col   : int

    def __repr__(self):
        return f"Token({self.type}, {self.value!r}, {self.line}:{self.col})"


# ─────────────────────────────────────────
#  LEXER
# ─────────────────────────────────────────

class LexError(Exception):
    pass


# ordered list of (token_type, compiled_regex)
TOKEN_PATTERNS = [
    ('SKIP',      re.compile(r'[ \t\r]+')),
    ('COMMENT',   re.compile(r'//[^\n]*')),
    ('NEWLINE',   re.compile(r'\n')),
    ('FLOAT_LIT', re.compile(r'\d+\.\d+')),
    ('TIME_LIT',  re.compile(r'\d+[sm]')),          # 2s  1m
    ('INT_LIT',   re.compile(r'\d+')),
    ('STR_LIT',   re.compile(r'"[^"]*"')),
    ('ARROW',     re.compile(r'->')),
    ('OP',        re.compile(r'==|!=|<=|>=|\+=|-=|\*=|/=|&&|\|\||[+\-*/%!<>=]')),
    ('LPAREN',    re.compile(r'\(')),
    ('RPAREN',    re.compile(r'\)')),
    ('LBRACE',    re.compile(r'\{')),
    ('RBRACE',    re.compile(r'\}')),
    ('LBRACKET',  re.compile(r'\[')),
    ('RBRACKET',  re.compile(r'\]')),
    ('SEMICOLON', re.compile(r';')),
    ('COMMA',     re.compile(r',')),
    ('DOT',       re.compile(r'\.')),
    ('AT',        re.compile(r'@')),
    ('COLON',     re.compile(r':')),
    ('IDENT',     re.compile(r'[A-Za-z_]\w*')),
]


def tokenize(source: str) -> list[Token]:
    tokens = []
    pos    = 0
    line   = 1
    line_start = 0

    def _is_word_boundary(idx: int) -> bool:
        return idx >= len(source) or not (source[idx].isalnum() or source[idx] == '_')

    while pos < len(source):
        matched = False

        # raw C injection blocks: c header/global/setup/loop { ... }
        if source[pos] == 'c' and _is_word_boundary(pos + 1):
            m = re.match(r'c\b\s+(header|global|setup|loop)\b\s*', source[pos:])
            if m:
                brace_pos = pos + len(m.group(0))
                if brace_pos < len(source) and source[brace_pos] == '{':
                    start_line = line
                    start_col = pos - line_start + 1
                    scope = m.group(1)
                    scan_pos = brace_pos
                    depth = 0
                    scan_line = line
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
                        elif ch == '"' or ch == "'":
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
                        elif source[scan_pos:scan_pos+2] == '//':
                            scan_pos += 2
                            while scan_pos < len(source) and source[scan_pos] != '\n':
                                scan_pos += 1
                        elif source[scan_pos:scan_pos+2] == '/*':
                            scan_pos += 2
                            while scan_pos + 1 < len(source) and source[scan_pos:scan_pos+2] != '*/':
                                if source[scan_pos] == '\n':
                                    scan_line += 1
                                    scan_line_start = scan_pos + 1
                                scan_pos += 1
                            scan_pos += 2 if scan_pos + 1 < len(source) else 1
                        elif source[scan_pos] == '\n':
                            scan_pos += 1
                            scan_line += 1
                            scan_line_start = scan_pos
                        else:
                            scan_pos += 1

                    if depth != 0:
                        raise LexError(f"Unterminated C block starting at line {start_line} column {start_col}")

                    raw_code = source[brace_pos + 1:scan_pos - 1]
                    tok_type = TT.C_BLOCK
                    tokens.append(Token(tok_type, (scope, raw_code), start_line, start_col))
                    pos = scan_pos
                    line = scan_line
                    line_start = scan_line_start
                    matched = True
                    continue

        for ttype, pat in TOKEN_PATTERNS:
            m = pat.match(source, pos)
            if not m:
                continue

            col = pos - line_start + 1
            text = m.group(0)

            if ttype == 'SKIP' or ttype == 'COMMENT':
                pass  # discard

            elif ttype == 'NEWLINE':
                line += 1
                line_start = pos + 1

            elif ttype == 'TIME_LIT':
                # convert  200s → 200000,  1m → 60000
                suffix = text[-1]
                ms = int(text[:-1]) * TIME_SUFFIX[suffix]
                tokens.append(Token(TT.INT_LIT, ms, line, col))

            elif ttype == 'FLOAT_LIT':
                tokens.append(Token(TT.FLOAT_LIT, float(text), line, col))

            elif ttype == 'INT_LIT':
                tokens.append(Token(TT.INT_LIT, int(text), line, col))

            elif ttype == 'STR_LIT':
                tokens.append(Token(TT.STR_LIT, text[1:-1], line, col))  # strip quotes

            elif ttype == 'IDENT':
                if text in ('true', 'false'):
                    tokens.append(Token(TT.BOOL_LIT, text == 'true', line, col))
                elif text in KEYWORDS:
                    tokens.append(Token(TT.KEYWORD, text, line, col))
                else:
                    tokens.append(Token(TT.IDENT, text, line, col))

            else:
                tokens.append(Token(ttype, text, line, col))

            pos += len(text)
            matched = True
            break

        if not matched:
            raise LexError(f"Unexpected character {source[pos]!r} at line {line} col {pos - line_start + 1}")

    tokens.append(Token(TT.EOF, None, line, 0))
    return tokens
