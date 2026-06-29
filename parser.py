"""
IOTIFT Parser — Milestone 0

Consumes a token list from the lexer and builds an AST.
Recursive-descent, LL(1) with basic error recovery.
Backward-compatible with all existing .iot syntax.
"""

from __future__ import annotations
import sys
from lexer import Token, TT
from ast_nodes import *
from typing import List, Optional, Any, Tuple


# Math/stdlib functions — the parser checks IDENT names against this set.
_MATH_FUNCTIONS: frozenset = frozenset({
    'sin', 'cos', 'tan', 'sqrt', 'abs', 'pow',
    'floor', 'ceil', 'round', 'log', 'exp',
    'millis', 'micros',
    'min', 'max', 'clamp', 'map',
})


class ParseError(Exception):
    """Raised when the parser encounters unexpected input."""
    pass


class Parser:
    """Recursive-descent parser for the Iotift language."""

    def __init__(self, tokens: List[Token]) -> None:
        self._tokens = tokens
        self._pos = 0
        self.pwm_pins: set[str] = set()    # pin names declared with 'pwm' direction
        self._errors: List[str] = []        # collected errors for recovery
        self._had_error: bool = False

    # ─────────────────────────────────────────
    #  TOKEN-STREAM HELPERS
    # ─────────────────────────────────────────

    def _peek(self, offset: int = 0) -> Token:
        i = self._pos + offset
        return self._tokens[i] if i < len(self._tokens) else self._tokens[-1]

    def _advance(self) -> Token:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _check(self, ttype: str, value: Any = None) -> bool:
        tok = self._peek()
        if tok.type != ttype:
            return False
        return value is None or tok.value == value

    def _match(self, ttype: str, value: Any = None) -> bool:
        if self._check(ttype, value):
            self._advance()
            return True
        return False

    def _expect(self, ttype: str, value: Any = None) -> Token:
        tok = self._peek()
        if tok.type != ttype or (value is not None and tok.value != value):
            expected = f"{ttype}({value!r})" if value is not None else ttype
            got = f"'{tok.value}'" if tok.value is not None else tok.type
            raise ParseError(
                f"Line {tok.line} col {tok.col}: expected {expected}, got {got}"
            )
        return self._advance()

    def _expect_semi(self) -> Token:
        return self._expect(TT.SEMICOLON)

    def _at_end(self) -> bool:
        return self._peek().type == TT.EOF

    def _is_type_token(self) -> bool:
        """Check if current token is a type keyword (old or new)."""
        tok = self._peek()
        if tok.type == TT.TYPE_KW:
            return True
        if tok.type == TT.KEYWORD and tok.value in ('int', 'float', 'bool', 'str', 'void'):
            return True
        return False

    def _consume_type(self) -> str:
        """Consume a type token (KEYWORD or TYPE_KW) and return the type name."""
        tok = self._peek()
        if tok.type == TT.TYPE_KW:
            return self._advance().value
        if tok.type == TT.KEYWORD and tok.value in ('int', 'float', 'bool', 'str', 'void'):
            return self._advance().value
        # Unexpected — let caller handle
        return self._expect(TT.KEYWORD).value

    # ─────────────────────────────────────────
    #  ERROR RECOVERY
    # ─────────────────────────────────────────

    def _sync(self) -> None:
        """Skip tokens until we find a safe resynchronization point."""
        while not self._at_end():
            tok = self._peek()
            # Synchronize on statement boundaries
            if tok.type == TT.SEMICOLON:
                self._advance()
                return
            if tok.type == TT.RBRACE:
                self._advance()   # consume the closing brace
                return
            if tok.type == TT.LBRACE:
                self._advance()   # consume the opening brace
                return
            # Top-level keywords are safe restart points (don't consume)
            if tok.type == TT.KEYWORD and tok.value in (
                'pin', 'fn', 'struct', 'enum', 'const', 'let', 'var',
                'extern', 'on', 'every', 'loop', 'tick', 'import',
            ):
                return
            if tok.type in (TT.TYPE_KW, TT.AT):
                return
            self._advance()

    def _error(self, msg: str) -> None:
        """Record a parse error and attempt recovery."""
        self._had_error = True
        self._errors.append(msg)
        print(f"Parse error: {msg}", file=sys.stderr)
        self._sync()

    # ─────────────────────────────────────────
    #  PROGRAM
    # ─────────────────────────────────────────

    def parse(self) -> Program:
        prog = Program(line=1)
        while not self._at_end():
            try:
                node = self._parse_top_level()
                if node is not None:
                    prog.body.append(node)
            except ParseError as e:
                self._error(str(e))
        return prog

    def _parse_top_level(self) -> Optional[Node]:
        tok = self._peek()

        if tok.type == TT.AT:
            # Peek ahead to distinguish @device from @config
            next_tok = self._peek(1)
            if next_tok.type == TT.KEYWORD and next_tok.value == 'config':
                return self._parse_scheduler_config()
            return self._parse_device()
        if tok.type == TT.KEYWORD and tok.value == 'import':
            return self._parse_import()
        if tok.type == TT.KEYWORD and tok.value == 'pin':
            return self._parse_pin()
        if tok.type == TT.KEYWORD and tok.value in ('const',):
            return self._parse_var_decl()
        # void loop() — check BEFORE _is_type_token since void is a TYPE_KW
        if (tok.type == TT.TYPE_KW and tok.value == 'void') or (tok.type == TT.KEYWORD and tok.value == 'void'):
            return self._parse_void_loop()
        if self._is_type_token():
            return self._parse_var_decl()
        if tok.type == TT.KEYWORD and tok.value in ('let', 'var'):
            return self._parse_let_var_decl()
        if tok.type == TT.KEYWORD and tok.value == 'struct':
            return self._parse_struct()
        if tok.type == TT.KEYWORD and tok.value == 'enum':
            return self._parse_enum()
        if tok.type == TT.KEYWORD and tok.value == 'type':
            return self._parse_type_alias()
        if tok.type == TT.KEYWORD and tok.value == 'fn':
            return self._parse_fn_decl()
        if tok.type == TT.KEYWORD and tok.value == 'isr':
            return self._parse_fn_decl(isr=True)
        if tok.type == TT.KEYWORD and tok.value == 'extern':
            return self._parse_extern_fn()
        if tok.type == TT.KEYWORD and tok.value == 'tick':
            return self._parse_tick_block()
        if tok.type == TT.KEYWORD and tok.value == 'on':
            return self._parse_on()
        if tok.type == TT.KEYWORD and tok.value == 'every':
            return self._parse_every()
        if tok.type == TT.KEYWORD and tok.value == 'loop':
            return self._parse_loop_block()
        if tok.type == TT.C_BLOCK:
            return self._parse_c_block()
        if tok.type == TT.KEYWORD and tok.value in ('i2c', 'spi', 'uart'):
            return self._parse_peripheral()

        # Bare statements at top level (assign, print, call, etc.)
        return self._parse_statement()

    # ─────────────────────────────────────────
    #  TOP-LEVEL DECLARATIONS
    # ─────────────────────────────────────────

    def _parse_device(self) -> DeviceDecl:
        line = self._peek().line
        self._expect(TT.AT)
        tok = self._peek()
        if tok.type == TT.KEYWORD and tok.value == 'device':
            self._advance()
        else:
            self._expect(TT.IDENT)  # fallback
        name = self._expect(TT.IDENT).value
        return DeviceDecl(line=line, name=name)

    def _parse_scheduler_config(self) -> SchedulerConfig:
        """@config scheduler_slots = 16;"""
        line = self._peek().line
        self._expect(TT.AT)
        self._expect(TT.KEYWORD, 'config')
        key = self._expect(TT.IDENT).value
        self._expect(TT.OP, '=')
        value = self._expect(TT.INT_LIT).value
        self._expect_semi()
        return SchedulerConfig(line=line, key=key, value=value)

    def _parse_after_block(self) -> AfterBlock:
        """after 5s { ... }  —  standalone one-shot timer block."""
        line = self._peek().line
        self._expect(TT.KEYWORD, 'after')
        interval = self._expect(TT.INT_LIT).value  # time literal already in ms
        body = self._parse_block()
        return AfterBlock(line=line, interval=interval, body=body)

    def _parse_import(self) -> ImportDecl:
        line = self._peek().line
        self._expect(TT.KEYWORD, 'import')
        path = self._expect(TT.STR_LIT).value
        self._expect_semi()
        return ImportDecl(line=line, path=path)

    def _parse_pin(self) -> PinDecl:
        line = self._peek().line
        self._expect(TT.KEYWORD, 'pin')
        name = self._expect(TT.IDENT).value
        self._expect(TT.OP, '=')

        # direction keyword
        dir_tok = self._peek()
        if dir_tok.type in (TT.KEYWORD, TT.IDENT):
            direction = self._advance().value
        else:
            direction = self._expect(TT.KEYWORD).value

        number = self._expect(TT.INT_LIT).value

        # Optional PWM config: freq N resolution N
        pwm_freq = None
        pwm_resolution = None
        if direction == 'pwm':
            self.pwm_pins.add(name)
            if self._check(TT.KEYWORD, 'freq'):
                self._advance()
                pwm_freq = self._expect(TT.INT_LIT).value
            if self._check(TT.KEYWORD, 'resolution'):
                self._advance()
                pwm_resolution = self._expect(TT.INT_LIT).value

        # Optional pin config block: { pull: up, debounce: 50ms }
        config = PinConfig()
        if self._check(TT.LBRACE):
            config = self._parse_pin_config()

        self._expect_semi()
        return PinDecl(line=line, name=name, direction=direction, number=number,
                       pwm_freq=pwm_freq, pwm_resolution=pwm_resolution,
                       config=config)

    def _parse_pin_config(self) -> PinConfig:
        """Parse { pull: up, debounce: 50ms } configuration block."""
        config = PinConfig()
        self._expect(TT.LBRACE)
        while not self._check(TT.RBRACE) and not self._at_end():
            key_tok = self._peek()
            if key_tok.type not in (TT.IDENT, TT.KEYWORD):
                break
            key = self._advance().value
            self._expect(TT.COLON)

            if key == 'pull':
                val = self._expect(TT.IDENT if self._peek().type == TT.IDENT else TT.KEYWORD).value
                config.pull = val
            elif key == 'debounce':
                # Parse time literal like 50ms
                val = self._expect(TT.INT_LIT).value
                config.debounce_ms = val
            elif key == 'initial':
                val_tok = self._peek()
                if val_tok.type in (TT.IDENT, TT.KEYWORD):
                    config.initial = self._advance().value
                else:
                    config.initial = self._expect(TT.INT_LIT).value
            else:
                # Skip unknown key-value pair
                if self._peek().type in (TT.IDENT, TT.KEYWORD, TT.INT_LIT, TT.STR_LIT):
                    self._advance()
                else:
                    self._advance()  # skip unknown

            if not self._match(TT.COMMA):
                break
        self._expect(TT.RBRACE)
        return config

    def _parse_var_decl(self, consume_semi: bool = True) -> Union[VarDecl, ArrayDecl]:
        """Old-style: int x = 0;  /  const int X = 5;"""
        line = self._peek().line
        is_const = bool(self._match(TT.KEYWORD, 'const'))
        is_volatile = bool(self._match(TT.KEYWORD, 'volatile'))

        # Consume type (KEYWORD or TYPE_KW)
        vtype = self._consume_type()
        name = self._expect(TT.IDENT).value

        # ── array: int vals[10]; ──
        if self._match(TT.LBRACKET):
            size = self._expect(TT.INT_LIT).value
            self._expect(TT.RBRACKET)
            if consume_semi:
                self._expect_semi()
            return ArrayDecl(line=line, vtype=vtype, name=name, size=size)

        init = None
        if self._match(TT.OP, '='):
            init = self._parse_expr()
        if consume_semi:
            self._expect_semi()
        return VarDecl(line=line, vtype=vtype, name=name, init=init,
                       is_const=is_const, is_volatile=is_volatile)

    def _parse_let_var_decl(self, consume_semi: bool = True) -> VarDecl:
        """New-style: let x = 0;  /  var x: u32 = 5;"""
        line = self._peek().line
        is_mutable = self._peek().value == 'var'
        self._advance()  # consume 'let' or 'var'

        is_volatile = bool(self._match(TT.KEYWORD, 'volatile'))
        name = self._expect(TT.IDENT).value

        vtype = None
        if self._match(TT.COLON):
            vtype = self._consume_type()

        init = None
        if self._match(TT.OP, '='):
            init = self._parse_expr()
        if consume_semi:
            self._expect_semi()
        return VarDecl(line=line, vtype=vtype, name=name, init=init,
                       is_mutable=is_mutable, is_volatile=is_volatile)

    def _parse_struct(self) -> StructDecl:
        line = self._peek().line
        self._expect(TT.KEYWORD, 'struct')
        name = self._expect(TT.IDENT).value
        self._expect(TT.LBRACE)
        fields: List[VarDecl] = []
        while not self._check(TT.RBRACE) and not self._at_end():
            try:
                fields.append(self._parse_var_decl())   # always consumes its own ';'
            except ParseError as e:
                self._error(str(e))
        self._expect(TT.RBRACE)
        return StructDecl(line=line, name=name, fields=fields)

    def _parse_enum(self) -> EnumDecl:
        """enum Mode { WarmWhite, Rainbow = 5, Breathing }"""
        line = self._peek().line
        self._expect(TT.KEYWORD, 'enum')
        name = self._expect(TT.IDENT).value

        backing_type = None
        if self._match(TT.COLON):
            backing_type = self._consume_type()

        self._expect(TT.LBRACE)
        variants: List[Tuple[str, Optional[int]]] = []
        while not self._check(TT.RBRACE) and not self._at_end():
            var_name = self._expect(TT.IDENT).value
            value: Optional[int] = None
            if self._match(TT.OP, '='):
                value = self._expect(TT.INT_LIT).value
            variants.append((var_name, value))
            if not self._match(TT.COMMA):
                break
        self._expect(TT.RBRACE)
        return EnumDecl(line=line, name=name, variants=variants,
                        backing_type=backing_type)

    def _parse_type_alias(self) -> TypeAliasDecl:
        """type Celsius = f32;"""
        line = self._peek().line
        self._expect(TT.KEYWORD, 'type')
        name = self._expect(TT.IDENT).value
        self._expect(TT.OP, '=')
        aliased_type = self._consume_type()
        self._expect_semi()
        return TypeAliasDecl(line=line, name=name, aliased_type=aliased_type)

    def _parse_fn_decl(self, isr: bool = False) -> FnDecl:
        line = self._peek().line
        if isr:
            self._expect(TT.KEYWORD, 'isr')
        self._expect(TT.KEYWORD, 'fn')
        name = self._expect(TT.IDENT).value
        params = self._parse_param_list()
        return_type: Optional[str] = None
        is_void = True
        if self._match(TT.ARROW):
            return_type = self._consume_type()
            is_void = False
        body = self._parse_block()
        return FnDecl(line=line, name=name, params=params,
                      return_type=return_type, body=body,
                      is_void=is_void, is_isr=isr)

    def _parse_extern_fn(self) -> Optional[ExternFnDecl]:
        """extern fn name(params) -> type;"""
        line = self._peek().line
        self._expect(TT.KEYWORD, 'extern')
        self._expect(TT.KEYWORD, 'fn')
        name = self._expect(TT.IDENT).value
        params = self._parse_param_list()
        return_type: Optional[str] = None
        if self._match(TT.ARROW):
            return_type = self._consume_type()
        self._expect_semi()
        return ExternFnDecl(line=line, name=name, params=params, return_type=return_type)

    def _parse_void_loop(self) -> VoidLoop:
        """void loop() { ... } — DEPRECATED, use tick { ... }"""
        line = self._peek().line
        # void can be TYPE_KW or KEYWORD
        tok = self._peek()
        if tok.type in (TT.TYPE_KW, TT.KEYWORD) and tok.value == 'void':
            self._advance()
        else:
            raise ParseError(
                f"Line {tok.line} col {tok.col}: expected 'void', got '{tok.value}'",
                tok.line, tok.col
            )
        # 'loop' may be KEYWORD
        tok = self._peek()
        if tok.type == TT.KEYWORD and tok.value == 'loop':
            self._advance()
        else:
            self._expect(TT.IDENT)
        self._expect(TT.LPAREN)
        self._expect(TT.RPAREN)
        body = self._parse_block()
        print(f"Line {line}: warning: 'void loop()' is deprecated, use 'tick {{ ... }}' instead",
              file=sys.stderr)
        return VoidLoop(line=line, body=body)

    def _parse_tick_block(self) -> TickBlock:
        """tick { ... } — replacement for void loop()"""
        line = self._peek().line
        self._expect(TT.KEYWORD, 'tick')
        body = self._parse_block()
        return TickBlock(line=line, body=body)

    def _parse_on(self) -> Union[OnEvent, OnThreshold]:
        line = self._peek().line
        self._expect(TT.KEYWORD, 'on')
        pin = self._expect(TT.IDENT).value

        # ── on TEMP > 50.0 { ... }   (threshold style) ──
        if self._check(TT.OP):
            op = self._advance().value
            value = self._parse_primary()
            body = self._parse_block()
            return OnThreshold(line=line, pin=pin, op=op, value=value, body=body)

        # ── on BTN.press { ... }   (event style) ──
        self._expect(TT.DOT)
        event = self._expect(TT.IDENT if self._peek().type == TT.IDENT else TT.KEYWORD).value
        body = self._parse_block()
        return OnEvent(line=line, pin=pin, event=event, body=body)

    def _parse_every(self) -> EveryBlock:
        line = self._peek().line
        self._expect(TT.KEYWORD, 'every')
        interval = self._expect(TT.INT_LIT).value
        label: Optional[str] = None
        if self._match(TT.KEYWORD, 'as'):
            label = self._expect(TT.IDENT).value
        offset_ms: Optional[int] = None
        if self._match(TT.KEYWORD, 'offset'):
            offset_ms = self._expect(TT.INT_LIT).value
        body = self._parse_block()
        return EveryBlock(line=line, interval=interval, label=label,
                          body=body, offset_ms=offset_ms)

    def _parse_loop_block(self) -> LoopBlock:
        line = self._peek().line
        self._expect(TT.KEYWORD, 'loop')
        body = self._parse_block()
        return LoopBlock(line=line, body=body)

    def _parse_c_block(self) -> CBlockNode:
        line = self._peek().line
        tok = self._advance()
        scope, code = tok.value
        return CBlockNode(line=line, scope=scope, code=code)

    def _parse_peripheral(self) -> PeripheralDecl:
        """i2c bus0 { sda: 21, scl: 22, speed: 100kHz };"""
        line = self._peek().line
        periph_type = self._expect(TT.KEYWORD).value  # i2c | spi | uart
        name = self._expect(TT.IDENT).value

        config: dict = {}
        if self._check(TT.LBRACE):
            self._advance()
            while not self._check(TT.RBRACE) and not self._at_end():
                key = self._expect(TT.IDENT if self._peek().type == TT.IDENT else TT.KEYWORD).value
                self._expect(TT.COLON)
                val_tok = self._peek()
                if val_tok.type == TT.INT_LIT:
                    config[key] = self._advance().value
                elif val_tok.type in (TT.IDENT, TT.KEYWORD):
                    config[key] = self._advance().value
                else:
                    self._advance()  # skip unknown
                if not self._match(TT.COMMA):
                    break
            self._expect(TT.RBRACE)
        self._expect_semi()
        return PeripheralDecl(line=line, periph_type=periph_type, name=name, config=config)

    # ─────────────────────────────────────────
    #  BLOCKS & STATEMENTS
    # ─────────────────────────────────────────

    def _parse_block(self) -> List[Node]:
        self._expect(TT.LBRACE)
        stmts: List[Node] = []
        while not self._check(TT.RBRACE) and not self._at_end():
            try:
                s = self._parse_statement()
                if s is not None:
                    stmts.append(s)
            except ParseError as e:
                self._error(str(e))
        self._expect(TT.RBRACE)
        return stmts

    def _parse_statement(self) -> Optional[Node]:
        tok = self._peek()

        if tok.type == TT.KEYWORD:
            if tok.value in ('int', 'float', 'bool', 'str', 'const'):
                return self._parse_var_decl()
            if tok.value in ('let', 'var'):
                return self._parse_let_var_decl()
            if tok.value == 'if':
                return self._parse_if()
            if tok.value == 'while':
                return self._parse_while()
            if tok.value == 'for':
                return self._parse_for()
            if tok.value == 'loop':
                return self._parse_loop_block()
            if tok.value == 'return':
                return self._parse_return()
            if tok.value == 'break':
                self._advance()
                self._expect_semi()
                return BreakStmt(line=tok.line)
            if tok.value == 'continue':
                self._advance()
                self._expect_semi()
                return ContinueStmt(line=tok.line)
            if tok.value == 'stop':
                return self._parse_stop()
            if tok.value == 'print':
                return self._parse_print()
            if tok.value == 'println':
                return self._parse_print(newline=True)
            if tok.value == 'defer':
                return self._parse_defer()
            if tok.value == 'after':
                return self._parse_after_block()
            if tok.value == 'extern':
                return self._parse_extern_fn()
            if tok.value == 'enum':
                return self._parse_enum()
            if tok.value == 'struct':
                return self._parse_struct()
            if tok.value == 'volatile':
                return self._parse_var_decl()

        if tok.type == TT.TYPE_KW:
            return self._parse_var_decl()
        if tok.type == TT.C_BLOCK:
            return self._parse_c_block()
        if tok.type == TT.IDENT:
            return self._parse_assign_or_call()

        # Stray semicolons are harmless; skip them.
        if tok.type == TT.SEMICOLON:
            self._advance()
            return None

        raise ParseError(
            f"Line {tok.line} col {tok.col}: unexpected {tok.type} '{tok.value}'"
        )

    def _parse_if(self) -> IfStmt:
        line = self._peek().line
        self._expect(TT.KEYWORD, 'if')
        self._expect(TT.LPAREN)
        cond = self._parse_expr()
        self._expect(TT.RPAREN)
        then_body = self._parse_block()
        elif_clauses: List[tuple] = []
        else_body: Optional[List[Node]] = None

        while self._check(TT.KEYWORD, 'else'):
            self._advance()
            if self._check(TT.KEYWORD, 'if'):
                self._advance()
                self._expect(TT.LPAREN)
                ec = self._parse_expr()
                self._expect(TT.RPAREN)
                eb = self._parse_block()
                elif_clauses.append((ec, eb))
            else:
                else_body = self._parse_block()
                break

        return IfStmt(line=line, condition=cond, then_body=then_body,
                      elif_clauses=elif_clauses, else_body=else_body)

    def _parse_while(self) -> WhileStmt:
        line = self._peek().line
        self._expect(TT.KEYWORD, 'while')
        self._expect(TT.LPAREN)
        cond = self._parse_expr()
        self._expect(TT.RPAREN)
        body = self._parse_block()
        return WhileStmt(line=line, condition=cond, body=body)

    def _parse_for(self) -> ForStmt:
        line = self._peek().line
        self._expect(TT.KEYWORD, 'for')
        self._expect(TT.LPAREN)

        # ── init clause ──
        init: Optional[Node] = None
        if not self._check(TT.SEMICOLON):
            tok = self._peek()
            if tok.type == TT.KEYWORD and tok.value in ('int', 'float', 'bool', 'str', 'const', 'let', 'var'):
                if tok.value in ('let', 'var'):
                    init = self._parse_let_var_decl(consume_semi=False)
                else:
                    init = self._parse_var_decl(consume_semi=False)
            elif tok.type == TT.TYPE_KW:
                init = self._parse_var_decl(consume_semi=False)
            else:
                init = self._parse_assign_or_call(consume_semi=False)
        self._expect_semi()

        # ── condition clause ──
        cond = None
        if not self._check(TT.SEMICOLON):
            cond = self._parse_expr()
        self._expect_semi()

        # ── step clause ──
        step = None
        if not self._check(TT.RPAREN):
            step = self._parse_assign_or_call(consume_semi=False)

        self._expect(TT.RPAREN)
        body = self._parse_block()
        return ForStmt(line=line, init=init, condition=cond, step=step, body=body)

    def _parse_return(self) -> ReturnStmt:
        line = self._peek().line
        self._expect(TT.KEYWORD, 'return')
        value = None
        if not self._check(TT.SEMICOLON):
            value = self._parse_expr()
        self._expect_semi()
        return ReturnStmt(line=line, value=value)

    def _parse_stop(self) -> StopStmt:
        line = self._peek().line
        self._expect(TT.KEYWORD, 'stop')
        label = self._expect(TT.IDENT).value
        self._expect_semi()
        return StopStmt(line=line, label=label)

    def _parse_print(self, newline: bool = True) -> PrintStmt:
        line = self._peek().line
        self._advance()  # print or println
        self._expect(TT.LPAREN)
        value = self._parse_expr()
        self._expect(TT.RPAREN)
        self._expect_semi()
        return PrintStmt(line=line, value=value, newline=newline)

    def _parse_defer(self) -> DeferStmt:
        line = self._peek().line
        self._expect(TT.KEYWORD, 'defer')
        body = self._parse_block()
        return DeferStmt(line=line, body=body)

    # ─────────────────────────────────────────
    #  ASSIGN-OR-CALL  (disambiguated by lookahead)
    # ─────────────────────────────────────────

    def _parse_assign_or_call(self, consume_semi: bool = True) -> Node:
        """
        The workhorse for ident-prefixed statements and for-loop clauses.

        When *consume_semi* is False the trailing semicolon is left in the
        stream so the caller (e.g. the for-loop parser) can handle it.
        """
        line = self._peek().line
        name = self._expect(TT.IDENT).value

        def _semi() -> None:
            if consume_semi:
                self._expect_semi()

        # ── fn-call: name(args) ──
        if self._check(TT.LPAREN):
            args = self._parse_arg_list()
            _semi()
            return FnCall(line=line, name=name, args=args)

        # ── dot-suffix: name.member  /  name.method(args) ──
        if self._check(TT.DOT):
            return self._parse_dot_tail(name, line, consume_semi)

        # ── array-index: name[expr] ──
        if self._check(TT.LBRACKET):
            self._advance()
            idx = self._parse_expr()
            self._expect(TT.RBRACKET)
            # Only assignment makes sense after array-index in statement position
            self._expect(TT.OP, '=')
            value = self._parse_expr()
            _semi()
            return Assign(line=line,
                          target=ArrayAccess(name=name, index=idx, line=line),
                          value=value)

        # ── compound-assign: name += expr ──
        if self._check(TT.OP) and self._peek().value in ('+=', '-=', '*=', '/=',
                                                          '%=', '&=', '|=', '^='):
            op = self._advance().value
            value = self._parse_expr()
            _semi()
            return CompoundAssign(line=line, target=name, op=op, value=value)

        # ── plain-assign: name = expr  [after N] ──
        self._expect(TT.OP, '=')
        value = self._parse_expr()

        if self._check(TT.KEYWORD, 'after'):
            self._advance()
            delay = self._expect(TT.INT_LIT).value
            _semi()
            return AssignAfter(line=line, target=name, value=value, delay=delay)

        _semi()
        return Assign(line=line, target=name, value=value)

    def _parse_dot_tail(self, obj_name: str, line: int,
                        consume_semi: bool) -> Node:
        """
        Parse the tail after ``name.`` — either a member read, method call,
        PWM-specific call, or member assignment.

        Used from both ``_parse_assign_or_call`` and ``_parse_primary``.
        """
        self._expect(TT.DOT)
        tok_m = self._peek()
        if tok_m.type in (TT.IDENT, TT.KEYWORD):
            member = self._advance().value
        else:
            raise ParseError(
                f"Line {tok_m.line} col {tok_m.col}: "
                f"expected member name after '.', got {tok_m.type}"
            )

        def _semi() -> None:
            if consume_semi:
                self._expect_semi()

        # ── method call: obj.method(args) ──
        if self._check(TT.LPAREN):
            args = self._parse_arg_list()
            _semi()

            # Route PWM-specific methods to dedicated nodes.
            if obj_name in self.pwm_pins:
                if member == 'setup':
                    freq = args[0] if args else Literal(vtype='int', value=5000, line=line)
                    resolution = args[1] if len(args) > 1 else Literal(vtype='int', value=8, line=line)
                    return PwmSetup(line=line, pin=obj_name,
                                    freq=freq, resolution=resolution)
                if member == 'write':
                    value = args[0] if args else Literal(vtype='int', value=0, line=line)
                    return PwmWrite(line=line, pin=obj_name, value=value)

            return MethodCall(line=line, obj=obj_name, method=member, args=args)

        # ── member assign: obj.member = expr ──
        if self._check(TT.OP, '='):
            self._advance()
            value = self._parse_expr()
            _semi()
            return Assign(line=line,
                          target=MemberAccess(obj=obj_name, member=member, line=line),
                          value=value)

        # ── bare member access (expression context) ──
        _semi()
        return MemberAccess(obj=obj_name, member=member, line=line)

    # ─────────────────────────────────────────
    #  EXPRESSIONS  (Pratt-style precedence climbing)
    # ─────────────────────────────────────────

    def _parse_expr(self) -> Any:
        return self._parse_logical()

    def _parse_logical(self) -> Any:
        left = self._parse_comparison()
        while self._check(TT.OP) and self._peek().value in ('&&', '||'):
            op = self._advance().value
            right = self._parse_comparison()
            left = BinOp(left=left, op=op, right=right)
        return left

    def _parse_comparison(self) -> Any:
        left = self._parse_additive()
        while self._check(TT.OP) and self._peek().value in ('==', '!=', '<', '>', '<=', '>='):
            op = self._advance().value
            right = self._parse_additive()
            left = BinOp(left=left, op=op, right=right)
        return left

    def _parse_additive(self) -> Any:
        left = self._parse_multiplicative()
        while self._check(TT.OP) and self._peek().value in ('+', '-'):
            op = self._advance().value
            right = self._parse_multiplicative()
            left = BinOp(left=left, op=op, right=right)
        return left

    def _parse_multiplicative(self) -> Any:
        left = self._parse_unary()
        while self._check(TT.OP) and self._peek().value in ('*', '/', '%'):
            op = self._advance().value
            right = self._parse_unary()
            left = BinOp(left=left, op=op, right=right)
        return left

    def _parse_unary(self) -> Any:
        if self._check(TT.OP) and self._peek().value in ('!', '-'):
            op = self._advance().value
            operand = self._parse_unary()
            return UnaryOp(op=op, operand=operand)
        return self._parse_cast()

    def _parse_cast(self) -> Any:
        """expr as TYPE  —  type cast expression."""
        left = self._parse_primary()
        if self._match(TT.KEYWORD, 'as'):
            target_type = self._consume_type()
            return CastExpr(expr=left, target_type=target_type)
        return left

    # ─────────────────────────────────────────
    #  PRIMARY EXPRESSIONS
    # ─────────────────────────────────────────

    def _parse_primary(self) -> Any:
        tok = self._peek()

        # ── sizeof(TYPE) ──
        if tok.type == TT.KEYWORD and tok.value == 'sizeof':
            line = tok.line
            self._advance()
            self._expect(TT.LPAREN)
            if self._is_type_token():
                target = self._consume_type()
            else:
                target = self._parse_expr()
            self._expect(TT.RPAREN)
            return SizeOfExpr(line=line, target=target)

        # ── literals ──
        if tok.type == TT.INT_LIT:
            self._advance()
            return Literal(vtype='int', value=tok.value, line=tok.line)
        if tok.type == TT.FLOAT_LIT:
            self._advance()
            return Literal(vtype='float', value=tok.value, line=tok.line)
        if tok.type == TT.STR_LIT:
            self._advance()
            return Literal(vtype='str', value=tok.value, line=tok.line)
        if tok.type == TT.CHAR_LIT:
            self._advance()
            return Literal(vtype='char', value=tok.value, line=tok.line)
        if tok.type == TT.BOOL_LIT:
            self._advance()
            return Literal(vtype='bool', value=tok.value, line=tok.line)

        # ── identifier (possibly with tail) ──
        if tok.type == TT.IDENT:
            name = tok.value
            line = tok.line
            self._advance()

            # fn-call
            if self._check(TT.LPAREN):
                args = self._parse_arg_list()
                return FnCall(line=line, name=name, args=args)

            # dot-access (unified — same as statement context)
            if self._check(TT.DOT):
                return self._parse_dot_tail(name, line, consume_semi=False)

            # array-index
            if self._check(TT.LBRACKET):
                self._advance()
                idx = self._parse_expr()
                self._expect(TT.RBRACKET)
                return ArrayAccess(name=name, index=idx, line=line)

            return Identifier(name=name, line=line)

        # ── parenthesised expression ──
        if tok.type == TT.LPAREN:
            self._advance()
            expr = self._parse_expr()
            self._expect(TT.RPAREN)
            return expr

        # ── millis() ──
        if tok.type == TT.KEYWORD and tok.value == 'millis':
            line = tok.line
            self._advance()
            self._expect(TT.LPAREN)
            self._expect(TT.RPAREN)
            return MillisExpr(line=line)

        # ── math/stdlib functions (treated as IDENT by lexer) ──
        if tok.type == TT.IDENT and tok.value in _MATH_FUNCTIONS:
            func = tok.value
            line = tok.line
            self._advance()
            self._expect(TT.LPAREN)
            args: List[Any] = []
            if not self._check(TT.RPAREN):
                args.append(self._parse_expr())
                while self._check(TT.COMMA):
                    self._advance()
                    args.append(self._parse_expr())
            self._expect(TT.RPAREN)
            return MathExpr(func=func, args=args, line=line)

        raise ParseError(
            f"Line {tok.line} col {tok.col}: "
            f"unexpected {tok.type} '{tok.value}' in expression"
        )

    # ─────────────────────────────────────────
    #  HELPERS
    # ─────────────────────────────────────────

    def _parse_param_list(self) -> List[VarDecl]:
        self._expect(TT.LPAREN)
        params: List[VarDecl] = []
        while not self._check(TT.RPAREN):
            vtype = self._consume_type()
            name = self._expect(TT.IDENT).value
            params.append(VarDecl(vtype=vtype, name=name))
            if not self._match(TT.COMMA):
                break
        self._expect(TT.RPAREN)
        return params

    def _parse_arg_list(self) -> List[Any]:
        self._expect(TT.LPAREN)
        args: List[Any] = []
        while not self._check(TT.RPAREN):
            args.append(self._parse_expr())
            if not self._match(TT.COMMA):
                break
        self._expect(TT.RPAREN)
        return args
