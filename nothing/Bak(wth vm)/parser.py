"""
IOTIFT Parser
Consumes a token list from the lexer and builds an AST.
"""

from lexer  import Token, TT
from ast_nodes import *
from typing import List, Optional, Any


class ParseError(Exception):
    pass


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos    = 0

    # ─────────────────────────────────────────
    #  HELPERS
    # ─────────────────────────────────────────

    def peek(self, offset=0) -> Token:
        i = self.pos + offset
        if i < len(self.tokens):
            return self.tokens[i]
        return self.tokens[-1]  # EOF

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def check(self, ttype: str, value=None) -> bool:
        tok = self.peek()
        if tok.type != ttype:
            return False
        if value is not None and tok.value != value:
            return False
        return True

    def match(self, ttype: str, value=None) -> bool:
        if self.check(ttype, value):
            self.advance()
            return True
        return False

    def expect(self, ttype: str, value=None) -> Token:
        tok = self.peek()
        if tok.type != ttype or (value is not None and tok.value != value):
            expected = f"{ttype}({value!r})" if value else ttype
            if tok.type == 'EOF':
                raise ParseError(f"Line {tok.line}: Unexpected end of file, expected {expected}")
            elif tok.type == 'IDENT':
                raise ParseError(f"Line {tok.line}: Unexpected identifier '{tok.value}', expected {expected}")
            elif tok.type == 'NUMBER':
                raise ParseError(f"Line {tok.line}: Unexpected number '{tok.value}', expected {expected}")
            elif tok.type == 'STRING':
                raise ParseError(f"Line {tok.line}: Unexpected string '{tok.value}', expected {expected}")
            else:
                raise ParseError(f"Line {tok.line}: Unexpected '{tok.type}' ('{tok.value}'), expected {expected}")
        return self.advance()

    def expect_semi(self):
        self.expect(TT.SEMICOLON)

    def at_end(self) -> bool:
        return self.peek().type == TT.EOF

    # ─────────────────────────────────────────
    #  PROGRAM
    # ─────────────────────────────────────────

    def parse(self) -> Program:
        prog = Program(line=1)
        while not self.at_end():
            node = self.parse_top_level()
            if node:
                prog.body.append(node)
        return prog

    def parse_top_level(self) -> Optional[Node]:
        tok = self.peek()

        # @device esp32
        if tok.type == TT.AT:
            return self.parse_device()

        # import "file.iot";
        if tok.type == TT.KEYWORD and tok.value == 'import':
            return self.parse_import()

        # pin LED = output 12;
        if tok.type == TT.KEYWORD and tok.value == 'pin':
            return self.parse_pin()

        # const int / int / float / bool / str
        if tok.type == TT.KEYWORD and tok.value in ('const', 'int', 'float', 'bool', 'str'):
            return self.parse_var_decl()

        # struct Sensor { ... }
        if tok.type == TT.KEYWORD and tok.value == 'struct':
            return self.parse_struct()

        # fn name(...) { ... }
        if tok.type == TT.KEYWORD and tok.value == 'fn':
            return self.parse_fn_decl()

        # extern fn name(...);
        if tok.type == TT.KEYWORD and tok.value == 'extern':
            return self.parse_extern_fn()

        # void loop() { ... }
        if tok.type == TT.KEYWORD and tok.value == 'void':
            return self.parse_void_loop()

        # on BTN.press { ... }  /  on TEMP > 50 { ... }
        if tok.type == TT.KEYWORD and tok.value == 'on':
            return self.parse_on()

        # every 1000 { ... }
        if tok.type == TT.KEYWORD and tok.value == 'every':
            return self.parse_every()

        # loop { ... }
        if tok.type == TT.KEYWORD and tok.value == 'loop':
            return self.parse_loop_block()

        # raw C injection blocks
        if tok.type == TT.C_BLOCK:
            return self.parse_c_block()

        # bare statements at top level (assign, print, call)
        return self.parse_statement()

    # ─────────────────────────────────────────
    #  TOP-LEVEL CONSTRUCTS
    # ─────────────────────────────────────────

    def parse_device(self) -> DeviceDecl:
        line = self.peek().line
        self.expect(TT.AT)
        self.expect(TT.KEYWORD, 'device')
        name = self.expect(TT.IDENT).value
        return DeviceDecl(line=line, name=name)

    def parse_import(self) -> ImportDecl:
        line = self.peek().line
        self.expect(TT.KEYWORD, 'import')
        path = self.expect(TT.STR_LIT).value
        self.expect_semi()
        return ImportDecl(line=line, path=path)

    def parse_pin(self) -> PinDecl:
        line = self.peek().line
        self.expect(TT.KEYWORD, 'pin')
        name = self.expect(TT.IDENT).value
        self.expect(TT.OP, '=')
        direction = self.expect(TT.KEYWORD).value   # output | input | analog | i2c | spi | pwm
        number = self.expect(TT.INT_LIT).value
        self.expect_semi()
        return PinDecl(line=line, name=name, direction=direction, number=number)

    def parse_var_decl(self) -> VarDecl | ArrayDecl:
        line = self.peek().line
        is_const = False
        if self.check(TT.KEYWORD, 'const'):
            self.advance()
            is_const = True

        vtype = self.expect(TT.KEYWORD).value   # int | float | bool | str
        name  = self.expect(TT.IDENT).value

        # array: int vals[10];
        if self.match(TT.LBRACKET):
            size = self.expect(TT.INT_LIT).value
            self.expect(TT.RBRACKET)
            self.expect_semi()
            return ArrayDecl(line=line, vtype=vtype, name=name, size=size)

        init = None
        if self.match(TT.OP, '='):
            init = self.parse_expr()

        self.expect_semi()
        return VarDecl(line=line, vtype=vtype, name=name, init=init, is_const=is_const)

    def parse_struct(self) -> StructDecl:
        line = self.peek().line
        self.expect(TT.KEYWORD, 'struct')
        name = self.expect(TT.IDENT).value
        self.expect(TT.LBRACE)
        fields = []
        while not self.check(TT.RBRACE):
            fields.append(self.parse_var_decl())
        self.expect(TT.RBRACE)
        return StructDecl(line=line, name=name, fields=fields)

    def parse_fn_decl(self) -> FnDecl:
        line = self.peek().line
        self.expect(TT.KEYWORD, 'fn')
        name   = self.expect(TT.IDENT).value
        params = self.parse_param_list()

        return_type = None
        is_void     = True
        if self.match(TT.ARROW):
            return_type = self.expect(TT.KEYWORD).value
            is_void     = False

        body = self.parse_block()
        return FnDecl(line=line, name=name, params=params,
                      return_type=return_type, body=body, is_void=is_void)

    def parse_extern_fn(self) -> ExternFnDecl:
        line = self.peek().line
        self.expect(TT.KEYWORD, 'extern')
        self.expect(TT.KEYWORD, 'fn')
        name   = self.expect(TT.IDENT).value
        params = self.parse_param_list()

        return_type = None
        if self.match(TT.ARROW):
            return_type = self.expect(TT.KEYWORD).value

        self.expect_semi()
        return ExternFnDecl(line=line, name=name, params=params, return_type=return_type)

    def parse_void_loop(self) -> VoidLoop:
        line = self.peek().line
        self.expect(TT.KEYWORD, 'void')
        self.expect(TT.KEYWORD, 'loop')  # 'loop' is a keyword
        self.expect(TT.LPAREN)
        self.expect(TT.RPAREN)
        body = self.parse_block()
        return VoidLoop(line=line, body=body)

    def parse_on(self) -> OnEvent | OnThreshold:
        line = self.peek().line
        self.expect(TT.KEYWORD, 'on')
        pin = self.expect(TT.IDENT).value

        # on TEMP > 50.0 { ... }   threshold style
        if self.check(TT.OP):
            op    = self.advance().value
            value = self.parse_primary()
            body  = self.parse_block()
            return OnThreshold(line=line, pin=pin, op=op, value=value, body=body)

        # on BTN.press { ... }   event style
        self.expect(TT.DOT)
        event = self.expect(TT.IDENT).value   # press | release | change
        body  = self.parse_block()
        return OnEvent(line=line, pin=pin, event=event, body=body)

    def parse_every(self) -> EveryBlock:
        line = self.peek().line
        self.expect(TT.KEYWORD, 'every')
        interval = self.expect(TT.INT_LIT).value

        label = None
        if self.match(TT.KEYWORD, 'as'):
            label = self.expect(TT.IDENT).value

        body = self.parse_block()
        return EveryBlock(line=line, interval=interval, label=label, body=body)

    def parse_loop_block(self) -> LoopBlock:
        line = self.peek().line
        self.expect(TT.KEYWORD, 'loop')
        body = self.parse_block()
        return LoopBlock(line=line, body=body)

    # ─────────────────────────────────────────
    #  STATEMENTS
    # ─────────────────────────────────────────

    def parse_block(self) -> List[Node]:
        self.expect(TT.LBRACE)
        stmts = []
        while not self.check(TT.RBRACE) and not self.at_end():
            s = self.parse_statement()
            if s:
                stmts.append(s)
        self.expect(TT.RBRACE)
        return stmts

    def parse_statement(self) -> Optional[Node]:
        tok = self.peek()

        if tok.type == TT.KEYWORD:
            if tok.value in ('int', 'float', 'bool', 'str', 'const'):
                return self.parse_var_decl()
            if tok.value == 'if':
                return self.parse_if()
            if tok.value == 'while':
                return self.parse_while()
            if tok.value == 'for':
                return self.parse_for()
            if tok.value == 'loop':
                return self.parse_loop_block()
            if tok.value == 'return':
                return self.parse_return()
            if tok.value == 'break':
                self.advance(); self.expect_semi()
                return BreakStmt(line=tok.line)
            if tok.value == 'continue':
                self.advance(); self.expect_semi()
                return ContinueStmt(line=tok.line)
            if tok.value == 'stop':
                return self.parse_stop()
            if tok.value == 'print':
                return self.parse_print()
            if tok.value == 'extern':
                return self.parse_extern_fn()

        if tok.type == TT.C_BLOCK:
            return self.parse_c_block()
        if tok.type == TT.IDENT:
            return self.parse_assign_or_call()

        # skip stray semicolons
        if tok.type == TT.SEMICOLON:
            self.advance()
            return None

        if tok.type == 'EOF':
            raise ParseError(f"Line {tok.line}: Unexpected end of file")
        elif tok.type == 'IDENT':
            raise ParseError(f"Line {tok.line}: Unexpected identifier '{tok.value}'")
        elif tok.type == 'NUMBER':
            raise ParseError(f"Line {tok.line}: Unexpected number '{tok.value}'")
        elif tok.type == 'STRING':
            raise ParseError(f"Line {tok.line}: Unexpected string '{tok.value}'")
        else:
            raise ParseError(f"Line {tok.line}: Unexpected '{tok.type}' ('{tok.value}')")

    def parse_if(self) -> IfStmt:
        line = self.peek().line
        self.expect(TT.KEYWORD, 'if')
        self.expect(TT.LPAREN)
        cond = self.parse_expr()
        self.expect(TT.RPAREN)
        then_body = self.parse_block()

        elif_clauses = []
        else_body    = None

        while self.check(TT.KEYWORD, 'else'):
            self.advance()
            if self.check(TT.KEYWORD, 'if'):
                self.advance()
                self.expect(TT.LPAREN)
                ec = self.parse_expr()
                self.expect(TT.RPAREN)
                eb = self.parse_block()
                elif_clauses.append((ec, eb))
            else:
                else_body = self.parse_block()
                break

        return IfStmt(line=line, condition=cond, then_body=then_body,
                      elif_clauses=elif_clauses, else_body=else_body)

    def parse_while(self) -> WhileStmt:
        line = self.peek().line
        self.expect(TT.KEYWORD, 'while')
        self.expect(TT.LPAREN)
        cond = self.parse_expr()
        self.expect(TT.RPAREN)
        body = self.parse_block()
        return WhileStmt(line=line, condition=cond, body=body)

    def parse_for(self) -> ForStmt:
        line = self.peek().line
        self.expect(TT.KEYWORD, 'for')
        self.expect(TT.LPAREN)

        # init
        init = None
        if not self.check(TT.SEMICOLON):
            if self.check(TT.KEYWORD):
                init = self.parse_var_decl()
            else:
                init = self.parse_assign_or_call()
        else:
            self.expect_semi()

        # condition
        cond = None
        if not self.check(TT.SEMICOLON):
            cond = self.parse_expr()
        self.expect_semi()

        # step
        step = None
        if not self.check(TT.RPAREN):
            step = self.parse_assign_or_call(no_semi=True)

        self.expect(TT.RPAREN)
        body = self.parse_block()
        return ForStmt(line=line, init=init, condition=cond, step=step, body=body)

    def parse_return(self) -> ReturnStmt:
        line = self.peek().line
        self.expect(TT.KEYWORD, 'return')
        value = None
        if not self.check(TT.SEMICOLON):
            value = self.parse_expr()
        self.expect_semi()
        return ReturnStmt(line=line, value=value)

    def parse_stop(self) -> StopStmt:
        line = self.peek().line
        self.expect(TT.KEYWORD, 'stop')
        label = self.expect(TT.IDENT).value
        self.expect_semi()
        return StopStmt(line=line, label=label)

    def parse_print(self) -> PrintStmt:
        line = self.peek().line
        self.expect(TT.KEYWORD, 'print')
        self.expect(TT.LPAREN)
        value = self.parse_expr()
        self.expect(TT.RPAREN)
        self.expect_semi()
        return PrintStmt(line=line, value=value)

    def parse_assign_or_call(self, no_semi=False) -> Node:
        """
        Handles:
          LED = 1;
          LED = 0 after 200;
          count += 1;
          esp_restart();
          blink(3);
          temp.value = 0.0;
          vals[0] = 42;
        """
        line = self.peek().line
        name = self.expect(TT.IDENT).value

        # function call:  name(...);
        if self.check(TT.LPAREN):
            args = self.parse_arg_list()
            if not no_semi:
                self.expect_semi()
            return FnCall(line=line, name=name, args=args)

        # member access assign:  temp.value = ...;
        if self.check(TT.DOT):
            self.advance()
            member = self.expect(TT.IDENT).value
            # could be method call: TEMP.read()
            if self.check(TT.LPAREN):
                args = self.parse_arg_list()
                if not no_semi:
                    self.expect_semi()
                return FnCall(line=line, name=f"{name}.{member}", args=args)
            self.expect(TT.OP, '=')
            value = self.parse_expr()
            if not no_semi:
                self.expect_semi()
            return Assign(line=line, target=f"{name}.{member}", value=value)

        # array assign:  vals[0] = ...;
        if self.check(TT.LBRACKET):
            self.advance()
            idx = self.parse_expr()
            self.expect(TT.RBRACKET)
            self.expect(TT.OP, '=')
            value = self.parse_expr()
            if not no_semi:
                self.expect_semi()
            return Assign(line=line, target=ArrayAccess(name=name, index=idx), value=value)

        # compound assign:  count += 1;
        if self.check(TT.OP) and self.peek().value in ('+=', '-=', '*=', '/='):
            op = self.advance().value
            value = self.parse_expr()
            if not no_semi:
                self.expect_semi()
            return CompoundAssign(line=line, target=name, op=op, value=value)

        # normal assign:  LED = 1;   LED = 0 after 200;
        self.expect(TT.OP, '=')
        value = self.parse_expr()

        # after keyword
        if self.check(TT.KEYWORD, 'after'):
            self.advance()
            delay = self.expect(TT.INT_LIT).value
            if not no_semi:
                self.expect_semi()
            return AssignAfter(line=line, target=name, value=value, delay=delay)

        if not no_semi:
            self.expect_semi()
        return Assign(line=line, target=name, value=value)

    # ─────────────────────────────────────────
    #  EXPRESSIONS
    # ─────────────────────────────────────────

    def parse_expr(self) -> Any:
        return self.parse_logical()

    def parse_logical(self) -> Any:
        left = self.parse_comparison()
        while self.check(TT.OP) and self.peek().value in ('&&', '||'):
            op    = self.advance().value
            right = self.parse_comparison()
            left  = BinOp(left=left, op=op, right=right)
        return left

    def parse_comparison(self) -> Any:
        left = self.parse_additive()
        while self.check(TT.OP) and self.peek().value in ('==', '!=', '<', '>', '<=', '>='):
            op    = self.advance().value
            right = self.parse_additive()
            left  = BinOp(left=left, op=op, right=right)
        return left

    def parse_additive(self) -> Any:
        left = self.parse_multiplicative()
        while self.check(TT.OP) and self.peek().value in ('+', '-'):
            op    = self.advance().value
            right = self.parse_multiplicative()
            left  = BinOp(left=left, op=op, right=right)
        return left

    def parse_multiplicative(self) -> Any:
        left = self.parse_unary()
        while self.check(TT.OP) and self.peek().value in ('*', '/', '%'):
            op    = self.advance().value
            right = self.parse_unary()
            left  = BinOp(left=left, op=op, right=right)
        return left

    def parse_unary(self) -> Any:
        if self.check(TT.OP) and self.peek().value in ('!', '-'):
            op      = self.advance().value
            operand = self.parse_unary()
            return UnaryOp(op=op, operand=operand)
        return self.parse_primary()

    def parse_c_block(self) -> Node:
        line = self.peek().line
        tok = self.advance()
        scope, code = tok.value
        return CBlockNode(line=line, scope=scope, code=code)

    def parse_primary(self) -> Any:
        tok = self.peek()

        # literals
        if tok.type == TT.INT_LIT:
            self.advance()
            return Literal(vtype='int', value=tok.value, line=tok.line)

        if tok.type == TT.FLOAT_LIT:
            self.advance()
            return Literal(vtype='float', value=tok.value, line=tok.line)

        if tok.type == TT.STR_LIT:
            self.advance()
            return Literal(vtype='str', value=tok.value, line=tok.line)

        if tok.type == TT.BOOL_LIT:
            self.advance()
            return Literal(vtype='bool', value=tok.value, line=tok.line)

        # identifier, call, member, array
        if tok.type == TT.IDENT:
            self.advance()
            name = tok.value

            if self.check(TT.LPAREN):
                args = self.parse_arg_list()
                return FnCall(line=tok.line, name=name, args=args)

            if self.check(TT.DOT):
                self.advance()
                member = self.expect(TT.IDENT).value
                if self.check(TT.LPAREN):
                    args = self.parse_arg_list()
                    return FnCall(line=tok.line, name=f"{name}.{member}", args=args)
                return MemberAccess(obj=name, member=member, line=tok.line)

            if self.check(TT.LBRACKET):
                self.advance()
                idx = self.parse_expr()
                self.expect(TT.RBRACKET)
                return ArrayAccess(name=name, index=idx, line=tok.line)

            return Identifier(name=name, line=tok.line)

        # parenthesised expression
        if tok.type == TT.LPAREN:
            self.advance()
            expr = self.parse_expr()
            self.expect(TT.RPAREN)
            return expr

        if tok.type == 'EOF':
            raise ParseError(f"Line {tok.line}: Unexpected end of file in expression")
        elif tok.type == 'IDENT':
            raise ParseError(f"Line {tok.line}: Unexpected identifier '{tok.value}' in expression")
        elif tok.type == 'NUMBER':
            raise ParseError(f"Line {tok.line}: Unexpected number '{tok.value}' in expression")
        elif tok.type == 'STRING':
            raise ParseError(f"Line {tok.line}: Unexpected string '{tok.value}' in expression")
        else:
            raise ParseError(f"Line {tok.line}: Unexpected '{tok.type}' ('{tok.value}') in expression")

    # ─────────────────────────────────────────
    #  HELPERS
    # ─────────────────────────────────────────

    def parse_param_list(self) -> List[VarDecl]:
        self.expect(TT.LPAREN)
        params = []
        while not self.check(TT.RPAREN):
            vtype = self.expect(TT.KEYWORD).value
            name  = self.expect(TT.IDENT).value
            params.append(VarDecl(vtype=vtype, name=name))
            if not self.match(TT.COMMA):
                break
        self.expect(TT.RPAREN)
        return params

    def parse_arg_list(self) -> List[Any]:
        self.expect(TT.LPAREN)
        args = []
        while not self.check(TT.RPAREN):
            args.append(self.parse_expr())
            if not self.match(TT.COMMA):
                break
        self.expect(TT.RPAREN)
        return args
