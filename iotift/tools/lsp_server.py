"""
Iotift LSP Server — Language Server Protocol implementation.

Zero external dependencies. Communicates via JSON-RPC 2.0 over stdin/stdout.
Provides diagnostics, completion, hover, go-to-definition, references,
and document symbols for .iot files.

Usage:
    python -m iotift.tools.lsp_server          # launch from CLI
    iotift lsp                                  # launch via iotift CLI
"""

from __future__ import annotations

import json
import sys
import os
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple

# Add parent directories to path for imports when run directly
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_THIS_DIR)
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

from lexer import tokenize, LexError
from parser import Parser, ParseError
from ast_nodes import (
    Node, Program, PinDecl, VarDecl, ArrayDecl, StructDecl, FnDecl,
    ExternFnDecl, EnumDecl, TypeAliasDecl, OnEvent, OnThreshold,
    EveryBlock, AfterBlock, TickBlock, VoidLoop, LoopBlock,
    Assign, CompoundAssign, AssignAfter, IfStmt, WhileStmt, ForStmt,
    ReturnStmt, PrintStmt, FnCall, MethodCall, MathExpr, MillisExpr,
    Identifier, BinOp, UnaryOp, MemberAccess, ArrayAccess, Literal,
    CastExpr, SizeOfExpr, ExprStmt, BreakStmt, ContinueStmt, StopStmt,
    DeferStmt, PwmSetup, PwmWrite, CBlockNode, ImportDecl,
    DeviceDecl, SchedulerConfig, PeripheralDecl,
)


# ═══════════════════════════════════════════════════════════════════════
#  LSP PROTOCOL CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

class CompletionItemKind:
    TEXT = 1
    METHOD = 2
    FUNCTION = 3
    CONSTRUCTOR = 4
    FIELD = 5
    VARIABLE = 6
    CLASS = 7
    INTERFACE = 8
    MODULE = 9
    PROPERTY = 10
    UNIT = 11
    VALUE = 12
    ENUM = 13
    KEYWORD = 14
    SNIPPET = 15
    COLOR = 16
    FILE = 17
    REFERENCE = 18
    STRUCT = 22
    TYPE_PARAMETER = 25


class SymbolKind:
    FILE = 1
    MODULE = 2
    NAMESPACE = 3
    PACKAGE = 4
    CLASS = 5
    METHOD = 6
    PROPERTY = 7
    FIELD = 8
    CONSTRUCTOR = 9
    ENUM = 10
    INTERFACE = 11
    FUNCTION = 12
    VARIABLE = 13
    CONSTANT = 14
    STRING = 15
    NUMBER = 16
    BOOLEAN = 17
    ARRAY = 18
    OBJECT = 19
    KEY = 20
    NULL = 21
    ENUM_MEMBER = 22
    STRUCT = 23
    EVENT = 24
    OPERATOR = 25
    TYPE_PARAMETER = 26


class TextDocumentSyncKind:
    NONE = 0
    FULL = 1
    INCREMENTAL = 2


class DiagnosticSeverity:
    ERROR = 1
    WARNING = 2
    INFORMATION = 3
    HINT = 4


# ═══════════════════════════════════════════════════════════════════════
#  IOTIFT COMPLETION DATA
# ═══════════════════════════════════════════════════════════════════════

_KEYWORDS = [
    'let', 'var', 'const', 'fn', 'isr', 'extern', 'volatile',
    'return', 'if', 'else', 'while', 'for', 'loop', 'break', 'continue',
    'defer', 'tick', 'stop', 'print', 'println', 'import',
    'struct', 'enum', 'type', 'sizeof', 'as',
    'every', 'after', 'on', 'offset',
    'true', 'false', 'void',
    'device', 'config', 'pin',
    'input', 'output', 'analog', 'pwm', 'i2c', 'spi', 'uart',
    'pull', 'up', 'down', 'none',
    'rising', 'falling', 'press', 'release', 'change',
    'millis',
]

_TYPE_KEYWORDS = [
    ('u8', '8-bit unsigned integer'),
    ('u16', '16-bit unsigned integer'),
    ('u32', '32-bit unsigned integer'),
    ('u64', '64-bit unsigned integer'),
    ('i8', '8-bit signed integer'),
    ('i16', '16-bit signed integer'),
    ('i32', '32-bit signed integer'),
    ('i64', '64-bit signed integer'),
    ('f32', '32-bit floating point'),
    ('f64', '64-bit floating point'),
    ('int', 'Platform integer (prefer i32)'),
    ('float', 'Platform float (prefer f32)'),
    ('bool', 'Boolean true/false'),
    ('char', 'Single character'),
    ('str', 'String literal'),
    ('void', 'No return value'),
]

_TIME_UNITS = ['ms', 's', 'm', 'h']

_SNIPPETS = {
    'pin': 'pin ${1:NAME} = ${2|output,input,analog,pwm,i2c,spi|} ${3:NUMBER};',
    'pin_config': (
        'pin ${1:NAME} = ${2|output,input,analog,pwm|} ${3:NUMBER} {\n'
        '    pull: ${4|up,down,none|},\n'
        '    debounce: ${5:50}ms\n'
        '};'
    ),
    'every': 'every ${1:500}ms {\n    ${2}\n}',
    'every_named': 'every ${1:1}s as ${2:label} {\n    ${3}\n}',
    'every_offset': 'every ${1:1}s offset ${2:100}ms {\n    ${3}\n}',
    'after': 'after ${1:5}s {\n    ${2}\n}',
    'on_event': 'on ${1:PIN}.${2|press,release,change,rising,falling|} {\n    ${3}\n}',
    'on_threshold': 'on ${1:PIN} ${2|>,<,>=,<=,==|} ${3:50.0} {\n    ${4}\n}',
    'fn': 'fn ${1:name}(${2:params}) {\n    ${3}\n}',
    'fn_typed': 'fn ${1:name}(${2:params}) -> ${3:type} {\n    ${4}\n}',
    'isr_fn': 'isr fn ${1:name}() {\n    ${2}\n}',
    'extern_fn': 'extern fn ${1:name}(${2:params});',
    'struct': 'struct ${1:Name} {\n    ${2:field}: ${3:type},\n}',
    'enum': 'enum ${1:Name} {\n    ${2:Variant1},\n    ${3:Variant2} = ${4:5},\n}',
    'type_alias': 'type ${1:Alias} = ${2:u32};',
    'if': 'if (${1:condition}) {\n    ${2}\n}',
    'if_else': 'if (${1:condition}) {\n    ${2}\n} else {\n    ${3}\n}',
    'while': 'while (${1:condition}) {\n    ${2}\n}',
    'for': 'for (let ${1:i} = 0; ${1:i} < ${2:N}; ${1:i} += 1) {\n    ${3}\n}',
    'loop': 'loop {\n    ${1}\n}',
    'tick': 'tick {\n    ${1}\n}',
    'defer': 'defer {\n    ${1}\n}',
    'print': 'print("${1}");',
    'println': 'println("${1}");',
    'i2c': 'i2c ${1:bus} { sda: ${2:21}, scl: ${3:22}, speed: ${4:100kHz} };',
    'spi': 'spi ${1:bus} { mosi: ${2:23}, miso: ${3:19}, sck: ${4:18}, speed: ${5:10MHz} };',
    'uart': 'uart ${1:serial} { tx: ${2:17}, rx: ${3:16}, baud: ${4:9600} };',
    'wifi': 'wifi ${1:home} {\n    ssid: "${2:MyWiFi}",\n    password: "${3:mypassword}",\n};',
    'device': '@device ${1|esp32|}',
    'config': '@config scheduler_slots = ${1:16};',
}

# ═══════════════════════════════════════════════════════════════════════
#  JSON-RPC TRANSPORT
# ═══════════════════════════════════════════════════════════════════════

class LSPTransport:
    """Reads/writes LSP JSON-RPC messages over stdin/stdout."""

    def __init__(self, input_stream=None, output_stream=None):
        self._in = input_stream or sys.stdin.buffer
        self._out = output_stream or sys.stdout.buffer
        self._next_id = 1

    def read_message(self) -> Optional[dict]:
        """Read one LSP message. Returns None on EOF."""
        # Read Content-Length header
        content_length = None
        while True:
            line = self._in.readline()
            if not line:
                return None
            line = line.decode('utf-8').rstrip('\r\n')
            if line == '':
                break
            if line.lower().startswith('content-length:'):
                try:
                    content_length = int(line.split(':', 1)[1].strip())
                except ValueError:
                    pass

        if content_length is None:
            return None

        # Read body
        body = self._in.read(content_length)
        if not body:
            return None

        return json.loads(body.decode('utf-8'))

    def send_message(self, message: dict) -> None:
        """Send one LSP message."""
        body = json.dumps(message, default=str)
        content = f'Content-Length: {len(body.encode("utf-8"))}\r\n\r\n{body}'
        self._out.write(content.encode('utf-8'))
        self._out.flush()

    def send_notification(self, method: str, params: dict = None) -> None:
        self.send_message({
            'jsonrpc': '2.0',
            'method': method,
            'params': params or {},
        })

    def send_response(self, msg_id: Any, result: Any) -> None:
        self.send_message({
            'jsonrpc': '2.0',
            'id': msg_id,
            'result': result,
        })

    def send_error(self, msg_id: Any, code: int, message: str,
                   data: Any = None) -> None:
        err = {'code': code, 'message': message}
        if data is not None:
            err['data'] = data
        self.send_message({
            'jsonrpc': '2.0',
            'id': msg_id,
            'error': err,
        })

    def send_request(self, method: str, params: dict = None) -> int:
        msg_id = self._next_id
        self._next_id += 1
        self.send_message({
            'jsonrpc': '2.0',
            'id': msg_id,
            'method': method,
            'params': params or {},
        })
        return msg_id


# ═══════════════════════════════════════════════════════════════════════
#  POSITION HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _line_col_to_offset(source: str, line: int, col: int) -> int:
    """Convert 1-based line/col to 0-based string offset."""
    lines = source.split('\n')
    offset = 0
    for i in range(min(line - 1, len(lines))):
        offset += len(lines[i]) + 1
    offset += col - 1
    return min(offset, len(source))


def _offset_to_lsp_pos(source: str, offset: int) -> dict:
    """Convert 0-based string offset to LSP Position (0-based line/char)."""
    offset = min(offset, len(source))
    text_before = source[:offset]
    line = text_before.count('\n')
    last_newline = text_before.rfind('\n')
    if last_newline == -1:
        character = offset
    else:
        character = offset - last_newline - 1
    return {'line': line, 'character': character}


def _node_to_range(node: Node, source: str) -> dict:
    """Convert an AST node's 1-based line/col to LSP Range."""
    # Node uses 1-based line/col
    start_offset = _line_col_to_offset(source, node.line, node.col)
    end_offset = _line_col_to_offset(
        source,
        node.end_line or node.line,
        node.end_col or (node.col + 1),
    )
    return {
        'start': _offset_to_lsp_pos(source, start_offset),
        'end': _offset_to_lsp_pos(source, end_offset),
    }


def _node_pos(node: Node, source: str) -> dict:
    """Get LSP Position for a node's start (1-based to 0-based)."""
    offset = _line_col_to_offset(source, node.line, node.col)
    return _offset_to_lsp_pos(source, offset)


# ═══════════════════════════════════════════════════════════════════════
#  DOCUMENT STORE
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class DocumentInfo:
    """Cached analysis results for an open document."""
    uri: str
    source: str = ''
    version: int = 0
    tokens: list = field(default_factory=list)
    ast: list = field(default_factory=list)
    lex_errors: list = field(default_factory=list)
    parse_errors: list = field(default_factory=list)
    semantic_errors: list = field(default_factory=list)
    semantic_warnings: list = field(default_factory=list)
    lint_diagnostics: list = field(default_factory=list)
    symbol_table: Any = None

    @property
    def dirty(self) -> bool:
        return len(self.source) == 0


# ═══════════════════════════════════════════════════════════════════════
#  LSP SERVER
# ═══════════════════════════════════════════════════════════════════════

class IotiftLSPServer:
    """Language Server Protocol server for Iotift."""

    def __init__(self, transport: LSPTransport = None):
        self.transport = transport or LSPTransport()
        self.documents: Dict[str, DocumentInfo] = {}
        self._running = False
        self._root_path: Optional[str] = None
        self._root_uri: Optional[str] = None

        # Server capabilities
        self._capabilities = {
            'textDocumentSync': {
                'openClose': True,
                'change': TextDocumentSyncKind.FULL,
                'save': True,
            },
            'completionProvider': {
                'resolveProvider': False,
                'triggerCharacters': ['.', '{'],
            },
            'hoverProvider': True,
            'definitionProvider': True,
            'referencesProvider': True,
            'documentSymbolProvider': True,
            'workspaceSymbolProvider': False,
        }

    # ── MAIN LOOP ──────────────────────────

    def run(self) -> None:
        """Main event loop. Reads messages and dispatches."""
        self._running = True
        while self._running:
            message = self.transport.read_message()
            if message is None:
                break
            self._handle_message(message)

    def stop(self) -> None:
        self._running = False

    # ── MESSAGE DISPATCH ──────────────────

    def _handle_message(self, msg: dict) -> None:
        """Dispatch incoming JSON-RPC message."""
        method = msg.get('method', '')
        msg_id = msg.get('id')

        handler_name = f'_on_{method.replace("/", "_").replace("$", "_")}'
        handler = getattr(self, handler_name, None)

        if handler:
            try:
                result = handler(msg.get('params', {}))
                if msg_id is not None and result is not None:
                    self.transport.send_response(msg_id, result)
            except Exception as e:
                if msg_id is not None:
                    self.transport.send_error(
                        msg_id, -32603,
                        f'Internal error: {e}'
                    )
        elif msg_id is not None:
            self.transport.send_error(
                msg_id, -32601,
                f'Method not found: {method}'
            )

    # ── LIFE-CYCLE ─────────────────────────

    def _on_initialize(self, params: dict) -> dict:
        """Handle initialize request."""
        self._root_path = params.get('rootPath')
        self._root_uri = params.get('rootUri')

        return {
            'capabilities': self._capabilities,
            'serverInfo': {
                'name': 'iotift-lsp',
                'version': '1.0.0',
            },
        }

    def _on_initialized(self, params: dict) -> None:
        """Handle initialized notification."""
        pass

    def _on_shutdown(self, params: dict) -> dict:
        """Handle shutdown request."""
        return None

    def _on_exit(self, params: dict) -> None:
        """Handle exit notification."""
        self.stop()

    # ── TEXT DOCUMENT SYNC ─────────────────

    def _on_textDocument_didOpen(self, params: dict) -> None:
        """Handle document open."""
        doc = params.get('textDocument', {})
        uri = doc.get('uri', '')
        source = doc.get('text', '')
        version = doc.get('version', 0)

        info = DocumentInfo(uri=uri, source=source, version=version)
        self.documents[uri] = info
        self._analyze(info)
        self._publish_diagnostics(uri, info)

    def _on_textDocument_didChange(self, params: dict) -> None:
        """Handle document change (full sync)."""
        doc = params.get('textDocument', {})
        uri = doc.get('uri', '')
        version = doc.get('version', 0)
        changes = params.get('contentChanges', [])

        info = self.documents.get(uri)
        if info is None:
            info = DocumentInfo(uri=uri)
            self.documents[uri] = info

        if changes:
            info.source = changes[0].get('text', info.source)
        info.version = version
        self._analyze(info)
        self._publish_diagnostics(uri, info)

    def _on_textDocument_didClose(self, params: dict) -> None:
        """Handle document close."""
        doc = params.get('textDocument', {})
        uri = doc.get('uri', '')
        self.documents.pop(uri, None)
        # Clear diagnostics
        self.transport.send_notification('textDocument/publishDiagnostics', {
            'uri': uri,
            'diagnostics': [],
        })

    def _on_textDocument_didSave(self, params: dict) -> None:
        """Handle document save."""
        doc = params.get('textDocument', {})
        uri = doc.get('uri', '')
        info = self.documents.get(uri)
        if info:
            # Re-read from disk if possible
            path = _uri_to_path(uri)
            if path and os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        info.source = f.read()
                except Exception:
                    pass
            self._analyze(info)
            self._publish_diagnostics(uri, info)

    # ── DIAGNOSTICS ────────────────────────

    def _analyze(self, info: DocumentInfo) -> None:
        """
        Run full analysis pipeline on a document.
        Populates errors, warnings, and lint diagnostics.
        """
        source = info.source
        info.lex_errors = []
        info.parse_errors = []
        info.semantic_errors = []
        info.semantic_warnings = []
        info.lint_diagnostics = []
        info.tokens = []
        info.ast = []

        # ── Lex ──
        try:
            info.tokens = tokenize(source)
        except LexError as e:
            info.lex_errors.append({
                'line': getattr(e, 'line', 1),
                'col': getattr(e, 'col', 1),
                'end_line': getattr(e, 'line', 1),
                'end_col': getattr(e, 'col', 1) + 1,
                'message': f'Lex error: {e}',
            })
            return

        # ── Parse ──
        parser = Parser(info.tokens)
        try:
            info.ast = parser.parse()
        except ParseError as e:
            info.parse_errors.append({
                'line': getattr(e, 'line', 1),
                'col': getattr(e, 'col', 1),
                'end_line': getattr(e, 'line', 1),
                'end_col': getattr(e, 'col', 1) + 1,
                'message': f'Parse error: {e}',
            })
            # Still try to get partial AST if available
            if hasattr(e, 'ast') and e.ast:
                info.ast = e.ast
            else:
                return

        # Collect parse errors from parser's internal error list
        # (the parser uses error recovery, catching ParseError internally)
        if hasattr(parser, '_errors'):
            for err_msg in parser._errors:
                # Parse line/col from error message if possible
                m = re.match(r'Line (\d+) col (\d+): (.+)', err_msg)
                if m:
                    info.parse_errors.append({
                        'line': int(m.group(1)),
                        'col': int(m.group(2)),
                        'end_line': int(m.group(1)),
                        'end_col': int(m.group(2)) + 1,
                        'message': f'Parse error: {m.group(3)}',
                    })
                else:
                    info.parse_errors.append({
                        'line': 1, 'col': 1, 'end_line': 1, 'end_col': 100,
                        'message': f'Parse error: {err_msg}',
                    })

        # ── Semantic ──
        try:
            from semantic import SemanticAnalyzer
            analyzer = SemanticAnalyzer()
            analyzer.analyze(info.ast)

            for err in analyzer.errors():
                # Parse line info from error string: "Line N: error: message"
                m = re.match(r'Line (\d+): error: (.+)', str(err))
                if m:
                    info.semantic_errors.append({
                        'line': int(m.group(1)),
                        'col': 1,
                        'end_line': int(m.group(1)),
                        'end_col': 100,
                        'message': m.group(2),
                    })
                else:
                    info.semantic_errors.append({
                        'line': 1, 'col': 1, 'end_line': 1, 'end_col': 100,
                        'message': str(err),
                    })

            for w in analyzer.warnings():
                m = re.match(r'Line (\d+): warning: (.+)', str(w))
                if m:
                    info.semantic_warnings.append({
                        'line': int(m.group(1)),
                        'col': 1,
                        'end_line': int(m.group(1)),
                        'end_col': 100,
                        'message': m.group(2),
                    })
                else:
                    info.semantic_warnings.append({
                        'line': 1, 'col': 1, 'end_line': 1, 'end_col': 100,
                        'message': str(w),
                    })

            info.symbol_table = analyzer._symbols
        except Exception:
            pass

        # ── Lint ──
        try:
            from iotift.tools.linter import lint_source, LintSeverity
            info.lint_diagnostics = lint_source(source)
        except Exception:
            pass

    def _publish_diagnostics(self, uri: str, info: DocumentInfo) -> None:
        """Convert analysis results to LSP diagnostics and publish."""
        source = info.source
        diags = []

        # Lex errors → LSP errors
        for e in info.lex_errors:
            diags.append(_make_diagnostic(
                e, source, DiagnosticSeverity.ERROR, 'lexer'
            ))

        # Parse errors → LSP errors
        for e in info.parse_errors:
            diags.append(_make_diagnostic(
                e, source, DiagnosticSeverity.ERROR, 'parser'
            ))

        # Semantic errors → LSP errors
        for e in info.semantic_errors:
            diags.append(_make_diagnostic(
                e, source, DiagnosticSeverity.ERROR, 'semantic'
            ))

        # Semantic warnings → LSP warnings
        for w in info.semantic_warnings:
            diags.append(_make_diagnostic(
                w, source, DiagnosticSeverity.WARNING, 'semantic'
            ))

        # Lint diagnostics → LSP diagnostics
        for ld in info.lint_diagnostics:
            sev = {
                'error': DiagnosticSeverity.ERROR,
                'warning': DiagnosticSeverity.WARNING,
                'info': DiagnosticSeverity.INFORMATION,
            }.get(ld.severity.value, DiagnosticSeverity.INFORMATION)

            diags.append(_make_diagnostic(
                {
                    'line': ld.line,
                    'col': ld.col or 1,
                    'end_line': ld.end_line or ld.line,
                    'end_col': ld.end_col or (ld.col or 1) + 1,
                    'message': f'[{ld.rule}] {ld.message}',
                },
                source, sev, 'lint'
            ))

        self.transport.send_notification('textDocument/publishDiagnostics', {
            'uri': uri,
            'diagnostics': diags,
        })

    # ── COMPLETION ─────────────────────────

    def _on_textDocument_completion(self, params: dict) -> list:
        """Handle completion request."""
        doc_params = params.get('textDocument', {})
        position = params.get('position', {})
        uri = doc_params.get('uri', '')

        info = self.documents.get(uri)
        if info is None or info.dirty:
            return {'isIncomplete': True, 'items': []}

        line = position.get('line', 0)
        char = position.get('character', 0)

        source = info.source
        items = []

        # Determine context: are we completing after a '.'?
        context = _get_completion_context(source, line, char)

        if context == 'member':
            # Member access: provide fields/methods
            # We'd need deeper analysis; for now provide common members
            items = _make_member_completions(source, info)
        else:
            # Top-level or statement context
            items = _make_keyword_completions()
            items.extend(_make_type_completions())
            items.extend(_make_snippet_completions())
            items.extend(_make_symbol_completions(info))
            items.extend(_make_stdlib_completions())

        # Filter by prefix
        word_start = _find_word_start(source, line, char)
        prefix = source[word_start:_offset_from_lsp_pos(source, line, char)]

        if prefix:
            items = [
                item for item in items
                if _completion_label(item).lower().startswith(prefix.lower())
            ]

        return {
            'isIncomplete': False,
            'items': items[:100],
        }

    # ── HOVER ──────────────────────────────

    def _on_textDocument_hover(self, params: dict) -> Optional[dict]:
        """Handle hover request."""
        doc_params = params.get('textDocument', {})
        position = params.get('position', {})
        uri = doc_params.get('uri', '')

        info = self.documents.get(uri)
        if info is None or info.dirty:
            return None

        line = position.get('line', 0)
        char = position.get('character', 0)
        source = info.source

        # Find the identifier at this position
        word, word_range = _get_word_at_position(source, line, char)
        if not word:
            return None

        # Look up in AST for hover info
        hover_text = _find_hover_info(word, info)
        if hover_text:
            return {
                'contents': {
                    'kind': 'markdown',
                    'value': hover_text,
                },
                'range': word_range,
            }

        return None

    # ── GO-TO-DEFINITION ───────────────────

    def _on_textDocument_definition(self, params: dict) -> Optional[dict]:
        """Handle go-to-definition request."""
        doc_params = params.get('textDocument', {})
        position = params.get('position', {})
        uri = doc_params.get('uri', '')

        info = self.documents.get(uri)
        if info is None or info.dirty:
            return None

        line = position.get('line', 0)
        char = position.get('character', 0)
        source = info.source

        word, _ = _get_word_at_position(source, line, char)
        if not word:
            return None

        # Search AST for the definition of this symbol
        loc = _find_definition(word, info)
        if loc:
            return {
                'uri': uri,
                'range': loc,
            }

        return None

    # ── REFERENCES ─────────────────────────

    def _on_textDocument_references(self, params: dict) -> list:
        """Handle find references request."""
        doc_params = params.get('textDocument', {})
        position = params.get('position', {})
        uri = doc_params.get('uri', '')
        include_decl = params.get('context', {}).get('includeDeclaration', True)

        info = self.documents.get(uri)
        if info is None or info.dirty:
            return []

        line = position.get('line', 0)
        char = position.get('character', 0)
        source = info.source

        word, _ = _get_word_at_position(source, line, char)
        if not word:
            return []

        refs = _find_references(word, info)
        return [{'uri': uri, 'range': r} for r in refs]

    # ── DOCUMENT SYMBOLS ───────────────────

    def _on_textDocument_documentSymbol(self, params: dict) -> list:
        """Handle document symbols request (outline view)."""
        doc_params = params.get('textDocument', {})
        uri = doc_params.get('uri', '')

        info = self.documents.get(uri)
        if info is None or info.dirty:
            return []

        source = info.source
        symbols = _collect_document_symbols(info.ast, source)
        return symbols


# ═══════════════════════════════════════════════════════════════════════
#  COMPLETION HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _get_completion_context(source: str, lsp_line: int, lsp_char: int) -> str:
    """Determine completion context: 'member', 'type', or 'default'."""
    offset = _offset_from_lsp_pos(source, lsp_line, lsp_char)
    text_before = source[:offset]
    # Check if we're after a '.'
    stripped = text_before.rstrip()
    if stripped.endswith('.'):
        return 'member'
    # Check if we're in a type position (after ':', '->', 'as')
    if re.search(r'(:\s*|->\s*|as\s+)$', stripped):
        return 'type'
    return 'default'


def _offset_from_lsp_pos(source: str, lsp_line: int, lsp_char: int) -> int:
    """Convert LSP 0-based line/char to string offset."""
    lines = source.split('\n')
    offset = 0
    for i in range(min(lsp_line, len(lines))):
        offset += len(lines[i]) + 1
    offset += lsp_char
    return min(offset, len(source))


def _find_word_start(source: str, lsp_line: int, lsp_char: int) -> int:
    """Find the start offset of the word at the given position."""
    offset = _offset_from_lsp_pos(source, lsp_line, lsp_char)
    # Walk back to find word start
    i = offset
    while i > 0 and (source[i - 1].isalnum() or source[i - 1] == '_'):
        i -= 1
    return i


def _completion_label(item: dict) -> str:
    """Get the text label for a completion item."""
    return item.get('label', item.get('insertText', ''))


def _make_keyword_completions() -> list:
    """Generate keyword completion items."""
    items = []
    for kw in _KEYWORDS:
        items.append({
            'label': kw,
            'kind': CompletionItemKind.KEYWORD,
            'insertText': kw,
            'detail': 'Keyword',
        })
    return items


def _make_type_completions() -> list:
    """Generate type completion items."""
    items = []
    for tname, tdoc in _TYPE_KEYWORDS:
        items.append({
            'label': tname,
            'kind': CompletionItemKind.STRUCT,
            'insertText': tname,
            'detail': tdoc,
        })
    return items


def _make_snippet_completions() -> list:
    """Generate snippet completion items."""
    items = []
    for name, body in _SNIPPETS.items():
        label = name.replace('_', ' ')
        items.append({
            'label': label,
            'kind': CompletionItemKind.SNIPPET,
            'insertText': body,
            'insertTextFormat': 2,  # Snippet
            'detail': f'Iotift snippet: {label}',
        })
    return items


def _make_symbol_completions(info: DocumentInfo) -> list:
    """Generate completions from in-scope symbols (variables, functions, pins, structs)."""
    items = []
    seen = set()

    for node in _walk_all_nodes(info.ast):
        if isinstance(node, VarDecl) and node.name and node.name not in seen:
            seen.add(node.name)
            kind = CompletionItemKind.VALUE if node.is_const else CompletionItemKind.VARIABLE
            detail = f'Variable'
            if node.vtype:
                detail += f': {node.vtype}'
            items.append({
                'label': node.name,
                'kind': kind,
                'detail': detail,
            })
        elif isinstance(node, FnDecl) and node.name and node.name not in seen:
            seen.add(node.name)
            detail = f'fn {node.name}'
            if node.params:
                params_str = ', '.join(
                    f'{p.name}: {p.vtype or "?"}' for p in node.params
                )
                detail += f'({params_str})'
            else:
                detail += '()'
            if node.return_type:
                detail += f' -> {node.return_type}'
            items.append({
                'label': node.name,
                'kind': CompletionItemKind.FUNCTION,
                'detail': detail,
            })
        elif isinstance(node, ExternFnDecl) and node.name and node.name not in seen:
            seen.add(node.name)
            items.append({
                'label': node.name,
                'kind': CompletionItemKind.FUNCTION,
                'detail': f'extern fn {node.name}',
            })
        elif isinstance(node, PinDecl) and node.name and node.name not in seen:
            seen.add(node.name)
            items.append({
                'label': node.name,
                'kind': CompletionItemKind.PROPERTY,
                'detail': f'Pin ({node.direction})',
            })
        elif isinstance(node, StructDecl) and node.name and node.name not in seen:
            seen.add(node.name)
            items.append({
                'label': node.name,
                'kind': CompletionItemKind.STRUCT,
                'detail': f'struct {node.name}',
            })
        elif isinstance(node, EnumDecl) and node.name and node.name not in seen:
            seen.add(node.name)
            items.append({
                'label': node.name,
                'kind': CompletionItemKind.ENUM,
                'detail': f'enum {node.name}',
            })
        elif isinstance(node, TypeAliasDecl) and node.name and node.name not in seen:
            seen.add(node.name)
            items.append({
                'label': node.name,
                'kind': CompletionItemKind.TYPE_PARAMETER,
                'detail': f'type {node.name} = {node.aliased_type}',
            })
        elif isinstance(node, PeripheralDecl) and node.name and node.name not in seen:
            seen.add(node.name)
            items.append({
                'label': node.name,
                'kind': CompletionItemKind.INTERFACE,
                'detail': f'{node.periph_type} peripheral',
            })

    return items


def _make_stdlib_completions() -> list:
    """Generate completions for standard library functions."""
    stdlib = [
        ('millis', CompletionItemKind.FUNCTION, 'Returns milliseconds since boot'),
        ('micros', CompletionItemKind.FUNCTION, 'Returns microseconds since boot'),
        ('delay', CompletionItemKind.FUNCTION, 'Blocking delay in milliseconds'),
        ('delay_us', CompletionItemKind.FUNCTION, 'Blocking delay in microseconds'),
        ('digitalRead', CompletionItemKind.FUNCTION, 'Read digital pin value'),
        ('digitalWrite', CompletionItemKind.FUNCTION, 'Write digital pin value'),
        ('pinMode', CompletionItemKind.FUNCTION, 'Set pin mode'),
        ('toggle', CompletionItemKind.FUNCTION, 'Toggle digital pin output'),
        ('sin', CompletionItemKind.FUNCTION, 'Sine (math.h)'),
        ('cos', CompletionItemKind.FUNCTION, 'Cosine (math.h)'),
        ('tan', CompletionItemKind.FUNCTION, 'Tangent (math.h)'),
        ('sqrt', CompletionItemKind.FUNCTION, 'Square root (math.h)'),
        ('abs', CompletionItemKind.FUNCTION, 'Absolute value'),
        ('pow', CompletionItemKind.FUNCTION, 'Power (math.h)'),
        ('floor', CompletionItemKind.FUNCTION, 'Floor (math.h)'),
        ('ceil', CompletionItemKind.FUNCTION, 'Ceiling (math.h)'),
        ('round', CompletionItemKind.FUNCTION, 'Round (math.h)'),
        ('log', CompletionItemKind.FUNCTION, 'Natural log (math.h)'),
        ('exp', CompletionItemKind.FUNCTION, 'Exponential (math.h)'),
        ('serialBegin', CompletionItemKind.FUNCTION, 'Initialize serial'),
        ('serialPrint', CompletionItemKind.FUNCTION, 'Print to serial'),
        ('serialRead', CompletionItemKind.FUNCTION, 'Read from serial'),
        ('i2cBegin', CompletionItemKind.FUNCTION, 'Initialize I2C bus'),
        ('i2cRead', CompletionItemKind.FUNCTION, 'Read from I2C device'),
        ('i2cWrite', CompletionItemKind.FUNCTION, 'Write to I2C device'),
        ('i2cScan', CompletionItemKind.FUNCTION, 'Scan I2C bus'),
        ('spiBegin', CompletionItemKind.FUNCTION, 'Initialize SPI bus'),
        ('spiTransfer', CompletionItemKind.FUNCTION, 'Transfer SPI data'),
        ('pwmSetup', CompletionItemKind.FUNCTION, 'Setup PWM channel'),
        ('pwmWrite', CompletionItemKind.FUNCTION, 'Write PWM duty cycle'),
        ('pwmStop', CompletionItemKind.FUNCTION, 'Stop PWM output'),
    ]
    return [
        {
            'label': name,
            'kind': kind,
            'detail': doc,
        }
        for name, kind, doc in stdlib
    ]


def _make_member_completions(source: str, info: DocumentInfo) -> list:
    """Generate completions for member access (after '.')."""
    items = []
    # Pin members
    items.extend([
        {
            'label': 'press',
            'kind': CompletionItemKind.KEYWORD,
            'detail': 'Pin press event',
        },
        {
            'label': 'release',
            'kind': CompletionItemKind.KEYWORD,
            'detail': 'Pin release event',
        },
        {
            'label': 'change',
            'kind': CompletionItemKind.KEYWORD,
            'detail': 'Pin change event',
        },
        {
            'label': 'rising',
            'kind': CompletionItemKind.KEYWORD,
            'detail': 'Pin rising edge event',
        },
        {
            'label': 'falling',
            'kind': CompletionItemKind.KEYWORD,
            'detail': 'Pin falling edge event',
        },
        {
            'label': 'running',
            'kind': CompletionItemKind.PROPERTY,
            'detail': 'Timer running status',
        },
        {
            'label': 'stop',
            'kind': CompletionItemKind.METHOD,
            'detail': 'Stop timer',
        },
        {
            'label': 'start',
            'kind': CompletionItemKind.METHOD,
            'detail': 'Start timer',
        },
        {
            'label': 'setup',
            'kind': CompletionItemKind.METHOD,
            'detail': 'Setup PWM',
        },
        {
            'label': 'write',
            'kind': CompletionItemKind.METHOD,
            'detail': 'Write PWM value',
        },
        {
            'label': 'read',
            'kind': CompletionItemKind.METHOD,
            'detail': 'Read value',
        },
        # WiFi properties
        {
            'label': 'state',
            'kind': CompletionItemKind.PROPERTY,
            'detail': 'WiFi state machine state',
        },
        {
            'label': 'connected',
            'kind': CompletionItemKind.PROPERTY,
            'detail': 'WiFi connection status (bool)',
        },
        {
            'label': 'ip',
            'kind': CompletionItemKind.PROPERTY,
            'detail': 'Local IP address (str)',
        },
        {
            'label': 'rssi',
            'kind': CompletionItemKind.PROPERTY,
            'detail': 'Signal strength in dBm (int)',
        },
        {
            'label': 'channel',
            'kind': CompletionItemKind.PROPERTY,
            'detail': 'WiFi channel number (int)',
        },
        {
            'label': 'mac',
            'kind': CompletionItemKind.PROPERTY,
            'detail': 'WiFi MAC address (str)',
        },
        {
            'label': 'clients',
            'kind': CompletionItemKind.PROPERTY,
            'detail': 'Connected station count (AP mode)',
        },
        {
            'label': 'ssid',
            'kind': CompletionItemKind.PROPERTY,
            'detail': 'Configured SSID (str)',
        },
        # WiFi methods
        {
            'label': 'scan',
            'kind': CompletionItemKind.METHOD,
            'detail': 'Start WiFi scan (STA only)',
        },
        {
            'label': 'disconnect',
            'kind': CompletionItemKind.METHOD,
            'detail': 'Disconnect from WiFi',
        },
        # WiFi events (LSP kind 24 = Event)
        {
            'label': 'connect',
            'kind': 24,
            'detail': 'WiFi connected + IP obtained (STA)',
        },
        {
            'label': 'got_ip',
            'kind': 24,
            'detail': 'IP address assigned (STA)',
        },
        {
            'label': 'scan_done',
            'kind': 24,
            'detail': 'WiFi scan completed (STA)',
        },
        {
            'label': 'client_join',
            'kind': 24,
            'detail': 'Station connected to AP',
        },
        {
            'label': 'client_leave',
            'kind': 24,
            'detail': 'Station disconnected from AP',
        },
    ])
    return items


# ═══════════════════════════════════════════════════════════════════════
#  HOVER HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _get_word_at_position(source: str, lsp_line: int, lsp_char: int
                          ) -> Tuple[Optional[str], Optional[dict]]:
    """Extract the word at the given LSP position."""
    offset = _offset_from_lsp_pos(source, lsp_line, lsp_char)
    if offset >= len(source) or offset < 0:
        return None, None

    # If not on a word character, look around
    c = source[offset] if offset < len(source) else ''
    if not (c.isalnum() or c == '_'):
        if offset > 0 and (source[offset - 1].isalnum() or source[offset - 1] == '_'):
            offset -= 1
        else:
            return None, None

    # Find word boundaries
    start = offset
    while start > 0 and (source[start - 1].isalnum() or source[start - 1] == '_'):
        start -= 1
    end = offset
    while end < len(source) and (source[end].isalnum() or source[end] == '_'):
        end += 1

    word = source[start:end]
    if not word:
        return None, None

    word_range = {
        'start': _offset_to_lsp_pos(source, start),
        'end': _offset_to_lsp_pos(source, end),
    }
    return word, word_range


def _find_hover_info(word: str, info: DocumentInfo) -> Optional[str]:
    """Find hover documentation for a symbol."""
    for node in _walk_all_nodes(info.ast):
        if isinstance(node, FnDecl) and node.name == word:
            parts = [f'**fn {node.name}**']
            if node.params:
                params = ', '.join(
                    f'{p.name}: {p.vtype or "?"}' for p in node.params
                )
                parts.append(f'({params})')
            else:
                parts.append('()')
            if node.return_type and node.return_type != 'void':
                parts.append(f' → `{node.return_type}`')
            if node.is_isr:
                parts.append('\n\n*ISR function — runs in interrupt context*')
            if node.is_extern:
                parts.append('\n\n*External C function*')
            return ''.join(parts)

        elif isinstance(node, ExternFnDecl) and node.name == word:
            parts = [f'**extern fn {node.name}**']
            if node.params:
                params = ', '.join(
                    f'{p.name}: {p.vtype or "?"}' for p in node.params
                )
                parts.append(f'({params})')
            else:
                parts.append('()')
            if node.return_type and node.return_type != 'void':
                parts.append(f' → `{node.return_type}`')
            parts.append('\n\n*External C function declaration*')
            return ''.join(parts)

        elif isinstance(node, VarDecl) and node.name == word:
            parts = [f'**{"const" if node.is_const else "var"} {node.name}**']
            if node.vtype:
                parts.append(f': `{node.vtype}`')
            if node.is_volatile:
                parts.append(' *(volatile)*')
            if node.is_const:
                parts.append('\n\n*Compile-time constant*')
            return ''.join(parts)

        elif isinstance(node, PinDecl) and node.name == word:
            parts = [f'**pin {node.name}**']
            parts.append(f'\nDirection: `{node.direction}`')
            parts.append(f'\nPin number: `{node.number}`')
            if node.config.pull:
                parts.append(f'\nPull: `{node.config.pull}`')
            if node.config.debounce_ms:
                parts.append(f'\nDebounce: `{node.config.debounce_ms}ms`')
            return ''.join(parts)

        elif isinstance(node, StructDecl) and node.name == word:
            parts = [f'**struct {node.name}**']
            if node.fields:
                parts.append('\n\nFields:')
                for f in node.fields:
                    parts.append(f'\n- `{f.name}: {f.vtype or "?"}`')
            return ''.join(parts)

        elif isinstance(node, EnumDecl) and node.name == word:
            parts = [f'**enum {node.name}**']
            if node.backing_type:
                parts.append(f' : `{node.backing_type}`')
            if node.variants:
                parts.append('\n\nVariants:')
                for name, value in node.variants:
                    if value is not None:
                        parts.append(f'\n- `{name} = {value}`')
                    else:
                        parts.append(f'\n- `{name}`')
            return ''.join(parts)

        elif isinstance(node, TypeAliasDecl) and node.name == word:
            return f'**type {node.name}** = `{node.aliased_type}`'

        elif isinstance(node, PeripheralDecl) and node.name == word:
            parts = [f'**{node.periph_type} {node.name}**']
            if node.config:
                parts.append('\n\nConfiguration:')
                for k, v in node.config.items():
                    parts.append(f'\n- `{k}`: `{v}`')
            return ''.join(parts)

    # Check stdlib functions
    stdlib_hover = {
        'millis': '**millis()** → `u64`\n\nReturns milliseconds since device boot.',
        'micros': '**micros()** → `u64`\n\nReturns microseconds since device boot.',
        'delay': '**delay(ms: u32)**\n\nBlocking delay in milliseconds.',
        'delay_us': '**delay_us(us: u32)**\n\nBlocking delay in microseconds.',
        'digitalRead': '**digitalRead(pin: u8)** → `bool`\n\nRead digital pin state.',
        'digitalWrite': '**digitalWrite(pin: u8, value: bool)**\n\nSet digital pin output.',
        'pinMode': '**pinMode(pin: u8, mode: u8)**\n\nConfigure pin mode.',
        'sin': '**sin(x: f32)** → `f32`\n\nCompute sine of x (radians).',
        'cos': '**cos(x: f32)** → `f32`\n\nCompute cosine of x (radians).',
        'sqrt': '**sqrt(x: f32)** → `f32`\n\nCompute square root.',
        'abs': '**abs(x: f32)** → `f32`\n\nCompute absolute value.',
    }
    if word in stdlib_hover:
        return stdlib_hover[word]

    return None


# ═══════════════════════════════════════════════════════════════════════
#  GO-TO-DEFINITION HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _find_definition(word: str, info: DocumentInfo) -> Optional[dict]:
    """Find the definition location of a symbol."""
    for node in _walk_all_nodes(info.ast):
        if isinstance(node, (VarDecl, FnDecl, ExternFnDecl, PinDecl,
                              StructDecl, EnumDecl, TypeAliasDecl,
                              PeripheralDecl, ArrayDecl)):
            if getattr(node, 'name', '') == word:
                return _node_to_range(node, info.source)
    return None


# ═══════════════════════════════════════════════════════════════════════
#  REFERENCES HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _find_references(word: str, info: DocumentInfo) -> List[dict]:
    """Find all references to a symbol in the document."""
    refs = []

    for node in _walk_all_nodes(info.ast):
        # Variable/function definitions
        if isinstance(node, (VarDecl, FnDecl, ExternFnDecl, PinDecl,
                              StructDecl, EnumDecl, TypeAliasDecl,
                              PeripheralDecl, ArrayDecl)):
            if getattr(node, 'name', '') == word:
                refs.append(_node_to_range(node, info.source))

        # Identifier references
        if isinstance(node, Identifier) and node.name == word:
            # Don't double-count the definition (Identifier used in VarDecl.init, etc.)
            refs.append(_node_to_range(node, info.source))

        # Function calls
        if isinstance(node, FnCall) and node.name == word:
            refs.append(_node_to_range(node, info.source))

        # Assign targets (string targets)
        if isinstance(node, (Assign, CompoundAssign)):
            target_name = None
            if isinstance(node.target, str):
                target_name = node.target
            elif isinstance(node.target, Identifier):
                target_name = node.target.name
            if target_name == word:
                refs.append(_node_to_range(node, info.source))

    # Deduplicate by range
    seen = set()
    unique = []
    for r in refs:
        key = (r['start']['line'], r['start']['character'])
        if key not in seen:
            seen.add(key)
            unique.append(r)

    return unique


# ═══════════════════════════════════════════════════════════════════════
#  DOCUMENT SYMBOLS HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _collect_document_symbols(ast: list, source: str) -> list:
    """Collect document symbols for outline view."""
    symbols = []

    def _kind_for(node: Node) -> int:
        if isinstance(node, FnDecl):
            return SymbolKind.FUNCTION
        elif isinstance(node, ExternFnDecl):
            return SymbolKind.FUNCTION
        elif isinstance(node, VarDecl):
            return SymbolKind.CONSTANT if node.is_const else SymbolKind.VARIABLE
        elif isinstance(node, PinDecl):
            return SymbolKind.PROPERTY
        elif isinstance(node, StructDecl):
            return SymbolKind.STRUCT
        elif isinstance(node, EnumDecl):
            return SymbolKind.ENUM
        elif isinstance(node, TypeAliasDecl):
            return SymbolKind.TYPE_PARAMETER
        elif isinstance(node, PeripheralDecl):
            return SymbolKind.INTERFACE
        elif isinstance(node, EveryBlock):
            return SymbolKind.EVENT
        elif isinstance(node, AfterBlock):
            return SymbolKind.EVENT
        elif isinstance(node, OnEvent):
            return SymbolKind.EVENT
        elif isinstance(node, OnThreshold):
            return SymbolKind.EVENT
        elif isinstance(node, TickBlock):
            return SymbolKind.EVENT
        elif isinstance(node, ImportDecl):
            return SymbolKind.MODULE
        else:
            return SymbolKind.VARIABLE

    def _name_for(node: Node) -> str:
        if isinstance(node, (FnDecl, ExternFnDecl, VarDecl, PinDecl,
                              StructDecl, EnumDecl, TypeAliasDecl,
                              PeripheralDecl, ArrayDecl)):
            return getattr(node, 'name', 'unknown')
        elif isinstance(node, EveryBlock):
            return node.label or f'every {node.interval}ms'
        elif isinstance(node, AfterBlock):
            return f'after {node.interval}ms'
        elif isinstance(node, OnEvent):
            return f'on {node.pin}.{node.event}'
        elif isinstance(node, OnThreshold):
            return f'on {node.pin} {node.op} {node.value}'
        elif isinstance(node, TickBlock):
            return 'tick'
        elif isinstance(node, VoidLoop):
            return 'void loop'
        elif isinstance(node, ImportDecl):
            return f'import "{node.path}"'
        elif isinstance(node, DeviceDecl):
            return f'@device {node.name}'
        elif isinstance(node, SchedulerConfig):
            return f'@config {node.key}'
        else:
            return type(node).__name__

    def _detail_for(node: Node) -> str:
        if isinstance(node, FnDecl):
            params = ', '.join(
                f'{p.name}: {p.vtype or "?"}' for p in node.params
            )
            ret = f' -> {node.return_type}' if node.return_type and node.return_type != 'void' else ''
            return f'fn {node.name}({params}){ret}'
        elif isinstance(node, VarDecl):
            return f'{node.vtype or "?"} {node.name}'
        elif isinstance(node, PinDecl):
            return f'pin {node.name} ({node.direction})'
        elif isinstance(node, StructDecl):
            return f'struct {node.name}'
        elif isinstance(node, EnumDecl):
            return f'enum {node.name}'
        return ''

    # Program body is a list
    body = ast if isinstance(ast, list) else (ast.body if hasattr(ast, 'body') else [])

    for node in body:
        if node is None:
            continue
        try:
            name = _name_for(node)
            detail = _detail_for(node)
            kind = _kind_for(node)
            rng = _node_to_range(node, source)

            symbol = {
                'name': name,
                'kind': kind,
                'range': rng,
                'selectionRange': rng,
            }
            if detail:
                symbol['detail'] = detail

            # For structs and enums, include children (fields/variants)
            if isinstance(node, StructDecl):
                children = []
                for field in node.fields:
                    field_range = _node_to_range(field, source)
                    children.append({
                        'name': field.name,
                        'kind': SymbolKind.FIELD,
                        'detail': f'{field.vtype or "?"} {field.name}',
                        'range': field_range,
                        'selectionRange': field_range,
                    })
                if children:
                    symbol['children'] = children

            elif isinstance(node, EnumDecl):
                children = []
                for var_name, var_value in node.variants:
                    # Variants are tuples, not nodes — approximate range
                    children.append({
                        'name': var_name,
                        'kind': SymbolKind.ENUM_MEMBER,
                        'detail': f'{var_name} = {var_value}' if var_value is not None else var_name,
                        'range': rng,
                        'selectionRange': rng,
                    })
                if children:
                    symbol['children'] = children

            symbols.append(symbol)
        except Exception:
            continue

    return symbols


# ═══════════════════════════════════════════════════════════════════════
#  GENERAL HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _walk_all_nodes(node):
    """Generator that yields all AST nodes in depth-first order."""
    if node is None:
        return
    yield node

    if isinstance(node, list):
        for item in node:
            if isinstance(item, Node):
                yield from _walk_all_nodes(item)
            elif isinstance(item, tuple):
                for sub in item:
                    if isinstance(sub, Node):
                        yield from _walk_all_nodes(sub)
                    elif isinstance(sub, list):
                        for s in sub:
                            if isinstance(s, Node):
                                yield from _walk_all_nodes(s)
    elif isinstance(node, Node):
        for field_name in dir(node):
            if field_name.startswith('_'):
                continue
            try:
                value = getattr(node, field_name)
            except Exception:
                continue
            if isinstance(value, Node):
                yield from _walk_all_nodes(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, Node):
                        yield from _walk_all_nodes(item)
                    elif isinstance(item, tuple):
                        for sub in item:
                            if isinstance(sub, Node):
                                yield from _walk_all_nodes(sub)
                            elif isinstance(sub, list):
                                for s in sub:
                                    if isinstance(s, Node):
                                        yield from _walk_all_nodes(s)


def _make_diagnostic(err: dict, source: str, severity: int, source_name: str) -> dict:
    """Convert internal error dict to LSP Diagnostic."""
    line = err.get('line', 1)
    col = err.get('col', 1)
    end_line = err.get('end_line', line)
    end_col = err.get('end_col', col + 1)

    start_offset = _line_col_to_offset(source, line, col)
    end_offset = _line_col_to_offset(source, end_line, end_col)

    return {
        'range': {
            'start': _offset_to_lsp_pos(source, start_offset),
            'end': _offset_to_lsp_pos(source, end_offset),
        },
        'severity': severity,
        'source': source_name,
        'message': err.get('message', 'Unknown error'),
    }


def _uri_to_path(uri: str) -> Optional[str]:
    """Convert a file:// URI to a filesystem path."""
    if uri.startswith('file://'):
        path = uri[7:]
        # Handle Windows paths: file:///C:/... → C:/...
        if path.startswith('/') and len(path) > 2 and path[2] == ':':
            path = path[1:]
        return path
    return None


# ═══════════════════════════════════════════════════════════════════════
#  MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════

def main():
    """Entry point for the LSP server."""
    # Log startup info to stderr (stdout is used for LSP transport)
    print('Iotift LSP server starting...', file=sys.stderr)
    server = IotiftLSPServer()
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f'LSP server error: {e}', file=sys.stderr)
        raise
    finally:
        print('Iotift LSP server stopped.', file=sys.stderr)


if __name__ == '__main__':
    main()
