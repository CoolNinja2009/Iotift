"""
Import system tests — covers import resolution, selective imports,
circular import detection, path resolution, prelude, and edge cases.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from lexer import tokenize
from parser import Parser, ParseError
from semantic import SemanticAnalyzer
from codegen import CodeGen
from import_resolver import ImportResolver, ImportError


# ── helpers ─────────────────────────────────────────────────────

def resolve_and_analyze(main_source, imported_files=None, werror=False):
    """Run import resolution + semantic analysis on source.

    *imported_files* is a dict of path → source for files that will be
    written to disk temporarily.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        # Write main file
        main_path = os.path.join(tmpdir, 'main.iot')
        with open(main_path, 'w', encoding='utf-8') as f:
            f.write(main_source)

        # Write imported files
        if imported_files:
            for rel_path, source in imported_files.items():
                abs_path = os.path.join(tmpdir, rel_path)
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                with open(abs_path, 'w', encoding='utf-8') as f:
                    f.write(source)

        # Lex + parse main file
        with open(main_path, encoding='utf-8') as f:
            tokens = tokenize(f.read())
        ast = Parser(tokens).parse()

        # Resolve imports
        resolver = ImportResolver()
        # Override stdlib path so we don't accidentally load real stdlib
        resolver._find_stdlib = lambda fp: os.path.join(tmpdir, '__no_stdlib__')
        ast = resolver.resolve(ast, main_path)

        # Semantic analysis
        sa = SemanticAnalyzer(werror=werror)
        sa.analyze(ast)
        return sa, ast


def compile_with_imports(main_source, imported_files=None):
    """Full pipeline including import resolution, returns C code."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        main_path = os.path.join(tmpdir, 'main.iot')
        with open(main_path, 'w', encoding='utf-8') as f:
            f.write(main_source)

        if imported_files:
            for rel_path, source in imported_files.items():
                abs_path = os.path.join(tmpdir, rel_path)
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                with open(abs_path, 'w', encoding='utf-8') as f:
                    f.write(source)

        with open(main_path, encoding='utf-8') as f:
            tokens = tokenize(f.read())
        ast = Parser(tokens).parse()

        resolver = ImportResolver()
        resolver._find_stdlib = lambda fp: os.path.join(tmpdir, '__no_stdlib__')
        ast = resolver.resolve(ast, main_path)

        sa = SemanticAnalyzer()
        sa.analyze(ast)
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"

        gen = CodeGen()
        return gen.generate(ast)


# ════════════════════════════════════════════════════════════════
#  IMPORT-ALL TESTS
# ════════════════════════════════════════════════════════════════

class TestImportAll:
    """import "file.iot" — all top-level symbols are imported."""

    def test_import_variable(self):
        sa, ast = resolve_and_analyze(
            'import "lib.iot";\n'
            'every 500 { int x = answer; }\n',
            {'lib.iot': 'int answer = 42;\n'},
        )
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"

    def test_import_function_and_call(self):
        sa, ast = resolve_and_analyze(
            'import "lib.iot";\n'
            'every 500 { add(2, 3); }\n',
            {'lib.iot': 'fn add(int a, int b) -> int { return a + b; }\n'},
        )
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"

    def test_import_multiple_symbols(self):
        sa, ast = resolve_and_analyze(
            'import "lib.iot";\n'
            'every 500 { int x = FOO; float y = bar; }\n',
            {'lib.iot': 'int FOO = 1;\nfloat bar = 2.5;\n'},
        )
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"

    def test_import_struct(self):
        sa, ast = resolve_and_analyze(
            'import "lib.iot";\n'
            'every 500 { int x = width; }\n',
            {'lib.iot': 'struct Point { int x; int y; }\n'
                        'int width = 10;\n'},
        )
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"

    def test_import_extern_fn(self):
        sa, ast = resolve_and_analyze(
            'import "lib.iot";\n'
            'every 500 { int t = my_millis(); }\n',
            {'lib.iot': 'extern fn my_millis() -> int;\n'},
        )
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"

    def test_import_c_blocks_are_included(self):
        """C blocks from imported files should be included."""
        _, ast = resolve_and_analyze(
            'import "lib.iot";\n',
            {'lib.iot': 'c header { #include <special.h> }\n'},
        )
        # Check that a CBlockNode from the import is in the resolved body
        c_blocks = [n for n in ast.body if type(n).__name__ == 'CBlockNode']
        assert len(c_blocks) >= 1, "C block should be inlined from import"

    def test_import_preserves_other_nodes(self):
        """Non-import nodes in the main file are preserved."""
        sa, ast = resolve_and_analyze(
            'pin LED = output 2;\n'
            'import "lib.iot";\n'
            'every 500 { LED = 1; }\n',
            {'lib.iot': 'int x = 1;\n'},
        )
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"

    def test_codegen_with_import(self):
        """Full pipeline generates valid C with imports."""
        c = compile_with_imports(
            'import "lib.iot";\n'
            'pin LED = output 2;\n'
            'every 500 { int y = helper(); }\n',
            {'lib.iot': 'extern fn helper() -> int;\n'},
        )
        assert 'helper' in c
        assert 'LED' in c


# ════════════════════════════════════════════════════════════════
#  SELECTIVE IMPORT TESTS
# ════════════════════════════════════════════════════════════════

class TestSelectiveImport:
    """import { Name1, Name2 } from "file.iot" — only selected symbols."""

    def test_selective_import_single(self):
        sa, ast = resolve_and_analyze(
            'import { answer } from "lib.iot";\n'
            'every 500 { int x = answer; }\n',
            {'lib.iot': 'int answer = 42;\nint secret = 99;\n'},
        )
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"

    def test_selective_import_multiple(self):
        sa, ast = resolve_and_analyze(
            'import { add, PI } from "lib.iot";\n'
            'every 500 { int x = add(1, 2); float y = PI; }\n',
            {'lib.iot': 'fn add(int a, int b) -> int { return a + b; }\n'
                        'const float PI = 3.14;\n'
                        'int hidden = 0;\n'},
        )
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"

    def test_selective_import_excludes_other(self):
        """Non-selected symbols should not be visible."""
        sa, ast = resolve_and_analyze(
            'import { answer } from "lib.iot";\n'
            'every 500 { int x = secret; }\n',  # secret not imported
            {'lib.iot': 'int answer = 42;\nint secret = 99;\n'},
        )
        assert sa.has_errors(), "Should error: 'secret' not imported"

    def test_selective_import_nonexistent_name(self):
        """Selective import of a name not in the module should error."""
        with pytest.raises(ImportError, match='not exported'):
            resolve_and_analyze(
                'import { nonexistent } from "lib.iot";\n',
                {'lib.iot': 'int answer = 42;\n'},
            )

    def test_selective_import_empty_braces(self):
        """Empty selective import should work (import nothing)."""
        sa, ast = resolve_and_analyze(
            'import { } from "lib.iot";\n'
            'every 500 { }\n',
            {'lib.iot': 'int answer = 42;\n'},
        )
        # Should not error — just imports zero symbols
        assert not sa.has_errors()


# ════════════════════════════════════════════════════════════════
#  PATH RESOLUTION TESTS
# ════════════════════════════════════════════════════════════════

class TestPathResolution:
    """Import path resolution logic."""

    def test_relative_dot_slash(self):
        sa, ast = resolve_and_analyze(
            'import "./sub/lib.iot";\n'
            'every 500 { int x = val; }\n',
            {'sub/lib.iot': 'int val = 1;\n'},
        )
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"

    def test_relative_dot_dot_slash(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a subdirectory for the main file
            subdir = os.path.join(tmpdir, 'sub')
            os.makedirs(subdir)
            main_path = os.path.join(subdir, 'main.iot')
            with open(main_path, 'w', encoding='utf-8') as f:
                f.write('import "../sibling.iot";\nevery 500 { int x = val; }\n')
            # Create sibling next to subdir
            sibling_path = os.path.join(tmpdir, 'sibling.iot')
            with open(sibling_path, 'w', encoding='utf-8') as f:
                f.write('int val = 2;\n')

            with open(main_path, encoding='utf-8') as f:
                tokens = tokenize(f.read())
            ast = Parser(tokens).parse()

            resolver = ImportResolver()
            resolver._find_stdlib = lambda fp: os.path.join(tmpdir, '__no_stdlib__')
            ast = resolver.resolve(ast, main_path)

            sa = SemanticAnalyzer()
            sa.analyze(ast)
            assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"

    def test_file_not_found(self):
        with pytest.raises(ImportError, match='File not found'):
            resolve_and_analyze(
                'import "nonexistent.iot";\n',
            )

    def test_import_without_extension(self):
        """Bare name without .iot extension should still resolve."""
        sa, ast = resolve_and_analyze(
            'import "lib";\n'  # no .iot
            'every 500 { int x = val; }\n',
            {'lib.iot': 'int val = 10;\n'},
        )
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"


# ════════════════════════════════════════════════════════════════
#  CIRCULAR IMPORT TESTS
# ════════════════════════════════════════════════════════════════

class TestCircularImports:
    """Circular import detection."""

    def test_direct_circular(self):
        with pytest.raises(ImportError, match='Circular import'):
            resolve_and_analyze(
                'import "a.iot";\n',
                {
                    'a.iot': 'import "b.iot";\n',
                    'b.iot': 'import "a.iot";\n',
                },
            )

    def test_indirect_circular(self):
        with pytest.raises(ImportError, match='Circular import'):
            resolve_and_analyze(
                'import "a.iot";\n',
                {
                    'a.iot': 'import "b.iot";\n',
                    'b.iot': 'import "c.iot";\n',
                    'c.iot': 'import "a.iot";\n',
                },
            )

    def test_self_import(self):
        """A file importing itself should be detected as circular."""
        with pytest.raises(ImportError, match='Circular import'):
            resolve_and_analyze(
                'import "main.iot";\n',
            )


# ════════════════════════════════════════════════════════════════
#  NESTED IMPORT TESTS
# ════════════════════════════════════════════════════════════════

class TestNestedImports:
    """Imports within imported files."""

    def test_transitive_import(self):
        """A imports B, B imports C — A should see B's symbols but not C's
        unless B re-exports them (which import-all does)."""
        sa, ast = resolve_and_analyze(
            'import "b.iot";\n'
            'every 500 { int x = b_val + c_val; }\n',
            {
                'b.iot': 'import "c.iot";\nint b_val = 1;\n',
                'c.iot': 'int c_val = 2;\n',
            },
        )
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"

    def test_deeply_nested(self):
        sa, ast = resolve_and_analyze(
            'import "a.iot";\n'
            'every 500 { int x = a_val; }\n',
            {
                'a.iot': 'import "b.iot";\nint a_val = 1;\n',
                'b.iot': 'import "c.iot";\nint b_val = 2;\n',
                'c.iot': 'int c_val = 3;\n',
            },
        )
        assert not sa.has_errors(), f"Unexpected errors: {sa.errors()}"


# ════════════════════════════════════════════════════════════════
#  DUPLICATE / CONFLICT TESTS
# ════════════════════════════════════════════════════════════════

class TestImportConflicts:
    """Duplicate symbol detection across imports."""

    def test_duplicate_from_two_imports(self):
        """Two imports defining the same name but different kinds should error."""
        sa, ast = resolve_and_analyze(
            'import "a.iot";\n'
            'import "b.iot";\n'
            'every 500 { val = 1; }\n',
            {
                'a.iot': 'int val = 1;\n',
                'b.iot': 'fn val() -> int { return 2; }\n',
            },
        )
        assert sa.has_errors(), "Should error: 'val' defined as both var and fn"

    def test_duplicate_with_local(self):
        """Local declaration conflicting with imported symbol of different kind."""
        sa, ast = resolve_and_analyze(
            'import "lib.iot";\n'
            'fn val() -> int { return 10; }\n'
            'every 500 { int x = val(); }\n',
            {'lib.iot': 'int val = 42;\n'},
        )
        assert sa.has_errors(), "Should error: 'val' defined as both var and fn"


# ════════════════════════════════════════════════════════════════
#  PARSER TESTS (import syntax)
# ════════════════════════════════════════════════════════════════

class TestImportParsing:
    """Parser correctly handles both import syntax forms."""

    def test_parse_import_all(self):
        tokens = tokenize('import "lib.iot";\n')
        ast = Parser(tokens).parse()
        imports = [n for n in ast.body if type(n).__name__ == 'ImportDecl']
        assert len(imports) == 1
        assert imports[0].path == 'lib.iot'
        assert imports[0].selected_names is None

    def test_parse_selective_import(self):
        tokens = tokenize('import { foo, bar } from "lib.iot";\n')
        ast = Parser(tokens).parse()
        imports = [n for n in ast.body if type(n).__name__ == 'ImportDecl']
        assert len(imports) == 1
        assert imports[0].path == 'lib.iot'
        assert imports[0].selected_names == ['foo', 'bar']

    def test_parse_selective_import_single(self):
        tokens = tokenize('import { foo } from "lib.iot";\n')
        ast = Parser(tokens).parse()
        imports = [n for n in ast.body if type(n).__name__ == 'ImportDecl']
        assert len(imports) == 1
        assert imports[0].selected_names == ['foo']

    def test_parse_selective_import_empty(self):
        tokens = tokenize('import { } from "lib.iot";\n')
        ast = Parser(tokens).parse()
        imports = [n for n in ast.body if type(n).__name__ == 'ImportDecl']
        assert len(imports) == 1
        assert imports[0].selected_names == []

    def test_parse_import_missing_path_errors(self):
        tokens = tokenize('import;\n')
        parser = Parser(tokens)
        parser.parse()
        assert parser._had_error, "Should report error for missing path"

    def test_parse_selective_import_missing_from(self):
        tokens = tokenize('import { foo } "lib.iot";\n')
        parser = Parser(tokens)
        parser.parse()
        assert parser._had_error, "Should report error for missing 'from'"
