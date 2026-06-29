"""
Import resolver for Iotift.

Resolves `import "file.iot"` and `import { Name } from "file.iot"`
statements by lexing/parsing the imported file and inlining its top-level
declarations into the importing AST. Runs before semantic analysis so the
rest of the pipeline sees a flat, fully-inlined AST.
"""

from __future__ import annotations

import os
from typing import List, Optional, Set, Dict

from lexer import tokenize, LexError
from parser import Parser, ParseError
from ast_nodes import (
    Program, ImportDecl, DeviceDecl, SchedulerConfig,
    VarDecl, ArrayDecl, FnDecl, ExternFnDecl,
    StructDecl, EnumDecl, PinDecl, PeripheralDecl,
    TypeAliasDecl, CBlockNode,
    EveryBlock, OnEvent, OnThreshold, AfterBlock, TickBlock,
)


class ImportError(Exception):
    """Raised when an import cannot be resolved."""
    pass


# Node types that carry a user-visible name and can be selectively imported.
_EXPORTABLE_TYPES = (
    VarDecl, ArrayDecl, FnDecl, ExternFnDecl,
    StructDecl, EnumDecl, PinDecl, PeripheralDecl,
    TypeAliasDecl,
)

# Node types that are always included from an imported file (infrastructure).
_ALWAYS_INCLUDE_TYPES = (CBlockNode,)


def _get_decl_name(node) -> Optional[str]:
    """Return the exportable name of a declaration, or None."""
    if isinstance(node, _EXPORTABLE_TYPES):
        return getattr(node, 'name', None)
    return None


class ImportResolver:
    """Resolves import declarations by inlining imported file ASTs."""

    def __init__(self):
        self._visited: Set[str] = set()       # files on current import stack
        self._ast_cache: Dict[str, Program] = {}  # path → parsed AST

    # ── public API ──────────────────────────────────────────────

    def resolve(self, ast: Program, file_path: str) -> Program:
        """Resolve all imports in *ast*, returning a new Program.

        *file_path* must be the absolute path of the source file so that
        relative imports are resolved correctly.
        """
        stdlib_dir = self._find_stdlib(file_path)
        new_body: List = []

        # ── prelude: time, math, gpio ──
        for prelude_name in ('time', 'math', 'gpio'):
            try:
                fake = ImportDecl(path=prelude_name)
                inlined = self._resolve_one(fake, file_path, stdlib_dir)
                for node in inlined:
                    node._imported_from = 'prelude'  # type: ignore[attr-defined]
                new_body.extend(inlined)
            except ImportError:
                pass  # prelude failures are non-fatal (stdlib may be incomplete)

        # ── user imports ──
        for node in ast.body:
            if isinstance(node, ImportDecl):
                try:
                    inlined = self._resolve_one(node, file_path, stdlib_dir)
                    for inlined_node in inlined:
                        inlined_node._imported_from = node.path  # type: ignore[attr-defined]
                    new_body.extend(inlined)
                except ImportError as e:
                    # Attach source location info
                    raise ImportError(
                        f"line {node.line}: {e}"
                    ) from None
            else:
                new_body.append(node)

        return Program(body=new_body)

    # ── internal ────────────────────────────────────────────────

    def _resolve_one(
        self, import_decl: ImportDecl, importer_path: str, stdlib_dir: str
    ) -> List:
        """Resolve a single import declaration to a list of AST nodes."""
        resolved_path = self._resolve_path(
            import_decl.path, importer_path, stdlib_dir
        )

        # Circular import detection
        if resolved_path in self._visited:
            chain = ' → '.join(
                f'"{os.path.basename(p)}"' for p in self._visited
            ) + f' → "{os.path.basename(resolved_path)}"'
            raise ImportError(f"Circular import detected: {chain}")

        self._visited.add(resolved_path)
        try:
            # Parse the file (cached)
            if resolved_path not in self._ast_cache:
                self._ast_cache[resolved_path] = self._parse_file(resolved_path)

            ast = self._ast_cache[resolved_path]

            # Recursively resolve any imports inside the imported file
            result: List = []
            for node in ast.body:
                if isinstance(node, ImportDecl):
                    nested = self._resolve_one(node, resolved_path, stdlib_dir)
                    result.extend(nested)
                elif isinstance(node, DeviceDecl) or isinstance(node, SchedulerConfig):
                    # Device and scheduler config belong to the owning file only
                    continue
                else:
                    result.append(node)

            # Apply selective-import filter
            if import_decl.selected_names is not None:
                result = self._filter_selected(
                    result, import_decl.selected_names, import_decl.path
                )

            return result
        finally:
            self._visited.discard(resolved_path)

    def _resolve_path(
        self, import_path: str, importer_path: str, stdlib_dir: str
    ) -> str:
        """Resolve an import path string to an absolute filesystem path.

        Resolution order:
        1. ``./`` or ``../`` — relative to importing file only
        2. Bare name — try relative to importing file, then stdlib directory
        """
        importer_dir = os.path.dirname(os.path.abspath(importer_path))

        # 1. Explicitly relative
        if import_path.startswith('./') or import_path.startswith('../'):
            resolved = os.path.normpath(os.path.join(importer_dir, import_path))
            if os.path.isfile(resolved):
                return resolved
            raise ImportError(
                f'File not found: "{import_path}" '
                f'(resolved to "{resolved}")'
            )

        # 2. Try relative to importing file (with and without .iot extension)
        relative = os.path.normpath(os.path.join(importer_dir, import_path))
        if os.path.isfile(relative):
            return relative
        if os.path.isfile(relative + '.iot'):
            return relative + '.iot'

        # 3. Try stdlib directory
        stdlib_path = os.path.normpath(os.path.join(stdlib_dir, import_path))
        if os.path.isfile(stdlib_path):
            return stdlib_path
        if os.path.isfile(stdlib_path + '.iot'):
            return stdlib_path + '.iot'

        raise ImportError(
            f'File not found: "{import_path}" '
            f'(looked in: "{importer_dir}", "{stdlib_dir}")'
        )

    def _parse_file(self, path: str) -> Program:
        """Lex and parse a .iot file, returning its AST."""
        try:
            with open(path, encoding='utf-8') as f:
                source = f.read()
        except OSError as e:
            raise ImportError(f'Cannot read "{path}": {e}') from None

        try:
            tokens = tokenize(source)
        except LexError as e:
            raise ImportError(f'Lex error in "{path}": {e}') from None

        try:
            return Parser(tokens).parse()
        except ParseError as e:
            raise ImportError(f'Parse error in "{path}": {e}') from None

    def _filter_selected(
        self, nodes: List, selected_names: List[str], import_path: str
    ) -> List:
        """Filter *nodes* to only those named in *selected_names*.

        C blocks and other infrastructure nodes are always included.
        """
        selected_set = set(selected_names)
        result: List = []
        found: Set[str] = set()

        for node in nodes:
            name = _get_decl_name(node)
            if name is not None and name in selected_set:
                result.append(node)
                found.add(name)
            elif isinstance(node, _ALWAYS_INCLUDE_TYPES):
                result.append(node)

        # Report names that were requested but not found
        missing = selected_set - found
        if missing:
            names = ', '.join(sorted(missing))
            raise ImportError(
                f'Name(s) {names} not exported by "{import_path}"'
            )

        return result

    def _find_stdlib(self, file_path: str) -> str:
        """Locate the stdlib directory on disk."""
        # The stdlib lives at iotift/stdlib/ relative to the project root.
        # import_resolver.py lives at the project root, so we can compute
        # relative to this file's location.
        resolver_dir = os.path.dirname(os.path.abspath(__file__))
        stdlib = os.path.join(resolver_dir, 'iotift', 'stdlib')
        if os.path.isdir(stdlib):
            return stdlib

        # Fallback: relative to the source file's directory
        project_dir = os.path.dirname(os.path.abspath(file_path))
        stdlib = os.path.join(project_dir, 'iotift', 'stdlib')
        return stdlib  # best effort — path resolution will error if wrong
