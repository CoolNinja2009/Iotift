#!/usr/bin/env python3
"""
Iotift Compiler — CLI entry point.

Usage:
    iotift check  <file.iot>              # Type-check only, no codegen
    iotift build  <file.iot> [-o out.c]   # Compile to C (default command)
    iotift flash  <file.iot>              # Compile + flash to device
    iotift fmt    <file.iot> [--check]    # Format source file
    iotift lint   <file.iot>              # Run linter
    iotift new    <project-name>          # Scaffold new project
    iotift version                        # Print version

    iotift <file.iot> [options]           # Legacy: equivalent to 'build'
"""

from __future__ import annotations

import sys
import os
import argparse
import subprocess
import site
import json
from typing import Optional

from lexer    import tokenize, LexError
from parser   import Parser, ParseError
from codegen  import CodeGen, __version__
from ir_lowering import IRLowering
from ir_optimizer import IROptimizer
from ir_codegen import IRCodeGen


# ─────────────────────────────────────────
#  ESP32 PORT AUTO-DETECTION
# ─────────────────────────────────────────

def _find_esp32_port() -> Optional[str]:
    """
    Scan system serial ports for an ESP32 by matching common USB-UART
    bridge manufacturers. Returns the device path of the first match,
    or None if no candidate is found.
    """
    try:
        from serial.tools import list_ports
    except ImportError:
        return None

    ports = list_ports.comports()
    keywords = ('CP210x', 'CH340', 'CH341', 'FTDI', 'Silicon Labs')
    matches: list = []

    for port in ports:
        desc  = (port.description  or '').upper()
        manuf = (port.manufacturer or '').upper()
        for kw in keywords:
            if kw.upper() in desc or kw.upper() in manuf:
                matches.append(port)
                break

    if not matches:
        return None

    selected = matches[0]
    if len(matches) > 1:
        print(f'Note: multiple ESP32 devices found; using {selected.device}')
    else:
        print(f'ESP32 detected on {selected.device}')
    return selected.device


# ─────────────────────────────────────────
#  PLATFORMIO HELPERS
# ─────────────────────────────────────────

def _ensure_platformio() -> str:
    """Make sure PlatformIO is installed; return path to the pio executable."""
    try:
        import platformio  # noqa: F401
    except ImportError:
        print('PlatformIO not found. Installing …')
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', 'platformio'],
        )
        if result.returncode != 0:
            print('Error: failed to install PlatformIO')
            sys.exit(1)
        print('PlatformIO installed.')

    scripts_dir = os.path.join(
        os.path.dirname(site.getusersitepackages()), 'Scripts',
    )
    pio = os.path.join(scripts_dir, 'pio.exe' if os.name == 'nt' else 'pio')
    return pio


def _ensure_pyserial() -> None:
    """Make sure pyserial is available for port auto-detection."""
    try:
        from serial.tools import list_ports  # noqa: F401
    except ImportError:
        print('pyserial not found. Installing …')
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', 'pyserial'],
        )
        if result.returncode != 0:
            print('Error: failed to install pyserial')
            sys.exit(1)
        print('pyserial installed.')


# ─────────────────────────────────────────
#  COMPILATION PIPELINE
# ─────────────────────────────────────────

def _read_source(filepath: str) -> str:
    """Read source file, exit on failure."""
    try:
        with open(filepath, encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        print(f'Error: file not found — {filepath}')
        sys.exit(1)


def _parse_source(source: str) -> list:
    """Lex and parse source, returning AST. Exit on error."""
    try:
        tokens = tokenize(source)
    except LexError as e:
        print(f'Lex error: {e}')
        sys.exit(1)

    try:
        parser = Parser(tokens)
        return parser.parse()
    except ParseError as e:
        print(f'Parse error: {e}')
        sys.exit(1)


def _resolve_imports(ast: list, source_path: str) -> list:
    """Resolve imports in the AST."""
    try:
        from import_resolver import ImportResolver
        resolver = ImportResolver()
        return resolver.resolve(ast, os.path.abspath(source_path))
    except ImportError as e:
        print(f'Import error: {e}', file=sys.stderr)
        sys.exit(1)


def _semantic_check(ast: list, werror: bool = False,
                    disabled_warnings: set = None) -> dict:
    """
    Run semantic analysis. Returns dict with 'errors', 'warnings', 'passed'.
    """
    from semantic import SemanticAnalyzer
    analyzer = SemanticAnalyzer(
        werror=werror,
        disabled_warnings=disabled_warnings or set(),
    )
    analyzer.analyze(ast)

    result = {
        'errors': list(analyzer.errors()),
        'warnings': list(analyzer.warnings()),
        'passed': not analyzer.has_errors(),
    }
    return result


def _generate_c(ast: list, device: str = 'esp32', baud: int = 115200,
                scheduler_slots: int = 16, direct_codegen: bool = False,
                no_optimize: bool = False, ir_dump: bool = False,
                debug: bool = False, source_path: str = '') -> tuple:
    """
    Generate C code from AST. Returns (c_code, source_map).
    """
    if direct_codegen:
        gen = CodeGen(device=device, baud_rate=baud,
                      scheduler_slots=scheduler_slots)
        c_code = gen.generate(ast)
        device_name = gen._device
        source_map = None
    else:
        lowering = IRLowering(scheduler_slots=scheduler_slots)
        ir_module = lowering.lower(ast)

        # Set source path for source maps
        if debug:
            ir_module.source_path = source_path

        if not no_optimize:
            optimizer = IROptimizer(ir_module)
            ir_module = optimizer.run_all()

        if ir_dump:
            _dump_ir(ir_module)

        ir_gen = IRCodeGen(device=device, baud_rate=baud,
                           scheduler_slots=scheduler_slots,
                           debug_source_map=debug)
        c_code = ir_gen.generate(ir_module)
        device_name = device
        source_map = ir_gen.source_map if debug else None

    return c_code, device_name, source_map


def _dump_ir(ir_module) -> None:
    """Print IR module structure to stdout."""
    print('=== IR Module ===')
    print(f'Device: {ir_module.device}')
    print(f'Globals: {len(ir_module.globals)}')
    print(f'Functions: {len(ir_module.functions)}')
    for fn in ir_module.functions:
        print(f'  fn {fn.name} ({len(fn.blocks)} blocks)')
        for bb in fn.blocks:
            print(f'    {bb.label}:')
            for instr in bb.instructions:
                print(f'      {type(instr).__name__}: {instr}')
    print(f'Every handlers: {len(ir_module.every_handlers)}')
    print(f'On-event handlers: {len(ir_module.on_event_handlers)}')
    print(f'Scheduler needed: {ir_module.scheduler_needed}')
    print()


# ─────────────────────────────────────────
#  PLATFORMIO PROJECT GENERATION
# ─────────────────────────────────────────

def _generate_platformio(source_path: str, c_code: str, baud: int) -> str:
    """Generate a PlatformIO project directory. Returns project dir path."""
    base_name   = os.path.splitext(os.path.basename(source_path))[0]
    project_dir = os.path.join(os.getcwd(), base_name + '_project')

    print(f'Generating PlatformIO project: {project_dir}')
    os.makedirs(project_dir, exist_ok=True)
    os.makedirs(os.path.join(project_dir, 'src'), exist_ok=True)
    os.makedirs(os.path.join(project_dir, 'include'), exist_ok=True)

    ini = (
        '[env:esp32]\n'
        'platform = espressif32\n'
        'board = esp32dev\n'
        'framework = arduino\n'
        f'monitor_speed = {baud}\n'
        'build_flags = -O2\n'
    )
    with open(os.path.join(project_dir, 'platformio.ini'), 'w', encoding='utf-8') as f:
        f.write(ini)

    with open(os.path.join(project_dir, 'src', 'main.cpp'), 'w', encoding='utf-8') as f:
        f.write(c_code)

    print(f'PlatformIO project ready: {project_dir}')
    return project_dir


def _flash_device(pio_cmd: str, project_dir: str, port: str) -> None:
    """Build and flash to the device."""
    print(f'Building and flashing to {port} …')
    cwd = os.getcwd()
    try:
        os.chdir(project_dir)
        result = subprocess.run([
            pio_cmd, 'run', '--target', 'upload',
            '--upload-port', port,
        ])
    finally:
        os.chdir(cwd)

    if result.returncode == 0:
        print('Flashing complete.')
    else:
        print('Error: flashing failed.')
        sys.exit(1)


# ─────────────────────────────────────────
#  SUBCOMMAND HANDLERS
# ─────────────────────────────────────────

def cmd_check(args) -> None:
    """Type-check only, no codegen."""
    source = _read_source(args.source)
    ast = _parse_source(source)
    ast = _resolve_imports(ast, args.source)

    result = _semantic_check(ast, werror=args.Werror,
                             disabled_warnings=set(args.Wno or []))

    if result['errors']:
        for err in result['errors']:
            print(err, file=sys.stderr)
        sys.exit(1)

    if result['warnings']:
        for w in result['warnings']:
            print(w, file=sys.stderr)

    print(f'Check passed: {args.source}')


def cmd_build(args) -> None:
    """Compile to C."""
    source = _read_source(args.source)
    ast = _parse_source(source)
    ast = _resolve_imports(ast, args.source)

    result = _semantic_check(ast, werror=args.Werror,
                             disabled_warnings=set(args.Wno or []))

    if result['errors']:
        for err in result['errors']:
            print(err, file=sys.stderr)
        sys.exit(1)

    if result['warnings']:
        for w in result['warnings']:
            print(w, file=sys.stderr)

    c_code, device_name, source_map = _generate_c(
        ast,
        device=args.target or args.device,
        baud=args.baud,
        scheduler_slots=args.scheduler_slots,
        direct_codegen=args.direct_codegen,
        no_optimize=args.no_optimize,
        ir_dump=args.ir_dump,
        debug=args.debug,
        source_path=os.path.abspath(args.source),
    )

    # Write output
    output_path = args.output
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(c_code)

    print(f'Compiled {args.source} -> {output_path} (target: {device_name})')

    # Write source map if debug enabled
    if source_map is not None:
        map_path = output_path + '.map.json'
        with open(map_path, 'w', encoding='utf-8') as f:
            json.dump(source_map, f, indent=2)
        print(f'Source map written: {map_path}')


def cmd_flash(args) -> None:
    """Compile + flash to device."""
    # Pre-flight
    pio_cmd = _ensure_platformio()
    _ensure_pyserial()

    port = args.port
    if not port:
        port = _find_esp32_port()
        if port is None:
            print('Error: no ESP32 detected. Connect your device or specify --port.')
            sys.exit(1)

    source = _read_source(args.source)
    ast = _parse_source(source)
    ast = _resolve_imports(ast, args.source)

    result = _semantic_check(ast, werror=args.Werror,
                             disabled_warnings=set(args.Wno or []))

    if result['errors']:
        for err in result['errors']:
            print(err, file=sys.stderr)
        sys.exit(1)

    if result['warnings']:
        for w in result['warnings']:
            print(w, file=sys.stderr)

    c_code, device_name, source_map = _generate_c(
        ast,
        device=args.target or args.device,
        baud=args.baud,
        scheduler_slots=args.scheduler_slots,
        direct_codegen=args.direct_codegen,
        no_optimize=args.no_optimize,
        ir_dump=args.ir_dump,
        debug=args.debug,
        source_path=os.path.abspath(args.source),
    )

    # Generate PlatformIO project and flash
    project_dir = _generate_platformio(args.source, c_code, args.baud)
    _flash_device(pio_cmd, project_dir, port)

    # Write source map if debug enabled
    if source_map is not None:
        map_path = os.path.join(project_dir, 'src', 'main.cpp.map.json')
        with open(map_path, 'w', encoding='utf-8') as f:
            json.dump(source_map, f, indent=2)
        print(f'Source map written: {map_path}')


def cmd_fmt(args) -> None:
    """Format source file."""
    from iotift.tools.formatter import format_file, check_format, FormatError

    try:
        if args.check:
            is_formatted = check_format(args.source)
            if is_formatted:
                print(f'{args.source}: formatted correctly')
            else:
                print(f'{args.source}: would be reformatted')
                sys.exit(1)
        else:
            formatted = format_file(args.source, in_place=True)
            print(f'Formatted: {args.source}')
    except FormatError as e:
        print(f'Format error: {e}', file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as e:
        print(f'Error: {e}', file=sys.stderr)
        sys.exit(1)


def cmd_lint(args) -> None:
    """Run linter."""
    from iotift.tools.linter import lint_file, LintSeverity

    diagnostics = lint_file(args.source)

    error_count = 0
    warning_count = 0
    info_count = 0

    for diag in diagnostics:
        if diag.severity == LintSeverity.ERROR:
            print(f'  ERROR: {diag}')
            error_count += 1
        elif diag.severity == LintSeverity.WARNING:
            print(f'  WARNING: {diag}')
            warning_count += 1
        else:
            print(f'  INFO: {diag}')
            info_count += 1

    total = len(diagnostics)
    if total == 0:
        print(f'{args.source}: no issues found')
    else:
        parts = []
        if error_count: parts.append(f'{error_count} error(s)')
        if warning_count: parts.append(f'{warning_count} warning(s)')
        if info_count: parts.append(f'{info_count} info(s)')
        print(f'\n{args.source}: {", ".join(parts)}')

    if error_count > 0:
        sys.exit(1)


def cmd_new(args) -> None:
    """Scaffold a new Iotift project."""
    project_name = args.name
    project_dir = os.path.join(os.getcwd(), project_name)

    if os.path.exists(project_dir):
        print(f'Error: directory already exists — {project_dir}')
        sys.exit(1)

    os.makedirs(project_dir)
    os.makedirs(os.path.join(project_dir, 'lib'), exist_ok=True)

    # Main source file
    main_iot = f'''@device esp32

pin LED = output 2;

every 500ms {{
    LED = 1;
    LED = 0 after 250ms;
}}
'''
    with open(os.path.join(project_dir, f'{project_name}.iot'), 'w', encoding='utf-8') as f:
        f.write(main_iot)

    # Project config
    config_toml = f'''# Iotift project configuration
name = "{project_name}"
version = "0.1.0"
device = "esp32"
'''
    with open(os.path.join(project_dir, 'iotift.toml'), 'w', encoding='utf-8') as f:
        f.write(config_toml)

    # .gitignore
    gitignore = '''# Generated C output
*.c
*_project/

# PlatformIO
.pio/
'''
    with open(os.path.join(project_dir, '.gitignore'), 'w', encoding='utf-8') as f:
        f.write(gitignore)

    print(f'Created Iotift project: {project_dir}')
    print(f'  {project_name}/{project_name}.iot  — main source file')
    print(f'  {project_name}/iotift.toml          — project configuration')
    print(f'  {project_name}/lib/                 — local libraries')
    print()
    print(f'Next: cd {project_name} && iotift build {project_name}.iot')


def cmd_lsp(args) -> None:
    """Launch the LSP server."""
    from iotift.tools.lsp_server import main as lsp_main
    lsp_main()


def cmd_debug(args) -> None:
    """Build with debug flags and optionally launch GDB."""
    source = _read_source(args.source)
    ast = _parse_source(source)
    ast = _resolve_imports(ast, args.source)

    result = _semantic_check(ast, werror=True, disabled_warnings=set())
    if result['errors']:
        for err in result['errors']:
            print(err, file=sys.stderr)
        sys.exit(1)

    device = args.target or args.device
    c_code, device_name, source_map = _generate_c(
        ast, device=device, debug=True,
        source_path=os.path.abspath(args.source),
    )

    # Write generated C with debug symbols
    base = os.path.splitext(os.path.basename(args.source))[0]
    output_path = base + '.c'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(c_code)
    print(f'Debug build: {args.source} -> {output_path} (target: {device_name})')

    # Write source map
    if source_map is not None:
        map_path = output_path + '.map.json'
        with open(map_path, 'w', encoding='utf-8') as f:
            json.dump(source_map, f, indent=2)
        print(f'Source map: {map_path}')

    # Generate PlatformIO project with debug flags
    project_dir = _generate_platformio_debug(args.source, c_code, args.baud)
    print(f'Debug project: {project_dir}')

    # Print GDB launch hint
    elf_path = os.path.join(project_dir, '.pio', 'build', 'esp32', 'firmware.elf')
    print()
    print('=== Debug Instructions ===')
    print(f'1. Build and flash:')
    print(f'   cd {project_dir} && pio run --target upload')
    print()
    if not args.no_flash:
        # Auto-flash with debug symbols
        pio_cmd = _ensure_platformio()
        port = args.port or _find_esp32_port()
        if port is None:
            print('Warning: no ESP32 detected. Connect your device or specify --port.')
            print(f'Project ready at: {project_dir}')
            sys.exit(0)
        _flash_device(pio_cmd, project_dir, port)
        print()
    print(f'2. Launch GDB:')
    print(f'   {args.gdb} {elf_path} -ex "target remote :3333"')
    print(f'   (Start OpenOCD in another terminal first)')
    print()
    print('Breakpoints in .iot source are mapped to C via --debug source maps.')


def _generate_platformio_debug(source_path: str, c_code: str, baud: int) -> str:
    """Generate a PlatformIO project with debug flags enabled."""
    base_name = os.path.splitext(os.path.basename(source_path))[0]
    project_dir = os.path.join(os.getcwd(), base_name + '_debug')

    os.makedirs(project_dir, exist_ok=True)
    os.makedirs(os.path.join(project_dir, 'src'), exist_ok=True)
    os.makedirs(os.path.join(project_dir, 'include'), exist_ok=True)

    ini = (
        '[env:esp32]\n'
        'platform = espressif32\n'
        'board = esp32dev\n'
        'framework = arduino\n'
        f'monitor_speed = {baud}\n'
        'build_flags = -O0 -g3 -ggdb\n'
        'debug_tool = esp-prog\n'
        'debug_init_break = tbreak setup\n'
    )
    with open(os.path.join(project_dir, 'platformio.ini'), 'w', encoding='utf-8') as f:
        f.write(ini)

    with open(os.path.join(project_dir, 'src', 'main.cpp'), 'w', encoding='utf-8') as f:
        f.write(c_code)

    return project_dir


def cmd_add(args) -> None:
    """Add a package dependency."""
    package = args.package
    version = args.version

    # Find or create iotift.toml
    toml_path = os.path.join(os.getcwd(), 'iotift.toml')
    if not os.path.exists(toml_path):
        print("Error: no iotift.toml found. Run 'iotift new <name>' first.")
        sys.exit(1)

    # Read existing config
    with open(toml_path, 'r', encoding='utf-8') as f:
        config = f.read()

    # Parse package spec
    if package.startswith('github.com/'):
        parts = package.replace('github.com/', '').split('/')
        if len(parts) >= 2:
            owner, repo = parts[0], parts[1]
            dep_line = f'"{owner}/{repo}" = "github.com/{owner}/{repo}"'
            if version:
                dep_line += f' @ {version}'
            else:
                dep_line += ' @ latest'
        else:
            print(f"Error: invalid package spec: {package}")
            sys.exit(1)
    else:
        dep_line = f'"{package}" = "{package}"'
        if version:
            dep_line += f' @ {version}'

    # Check if deps section exists
    if '[dependencies]' not in config:
        config += '\n[dependencies]\n'
    config += f'{dep_line}\n'

    with open(toml_path, 'w', encoding='utf-8') as f:
        f.write(config)

    print(f'Added dependency: {package}' + (f' @ {version}' if version else ''))
    print(f'Updated: {toml_path}')

    # Generate lock file
    _update_lockfile(os.getcwd())


def cmd_remove(args) -> None:
    """Remove a package dependency."""
    toml_path = os.path.join(os.getcwd(), 'iotift.toml')
    if not os.path.exists(toml_path):
        print("Error: no iotift.toml found.")
        sys.exit(1)

    with open(toml_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    new_lines = []
    removed = False
    for line in lines:
        if args.package in line and not removed:
            removed = True
            continue
        new_lines.append(line)

    if removed:
        with open(toml_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        print(f'Removed dependency: {args.package}')
        _update_lockfile(os.getcwd())
    else:
        print(f'Package "{args.package}" not found in dependencies.')


def cmd_update(args) -> None:
    """Update package dependencies."""
    toml_path = os.path.join(os.getcwd(), 'iotift.toml')
    if not os.path.exists(toml_path):
        print("Error: no iotift.toml found.")
        sys.exit(1)

    if args.package:
        print(f'Updating {args.package} to latest...')
    else:
        print('Updating all dependencies to latest...')

    # In a real implementation, this would fetch from the registry.
    # For now, update the lock file with current timestamps.
    _update_lockfile(os.getcwd())
    print('Dependencies updated.')
    print('  (Package registry at iotift.io/packages — coming soon)')


def _update_lockfile(project_dir: str) -> None:
    """Generate/update iotift.lock with resolved versions."""
    toml_path = os.path.join(project_dir, 'iotift.toml')
    lock_path = os.path.join(project_dir, 'iotift.lock')

    if not os.path.exists(toml_path):
        return

    from datetime import datetime, timezone

    with open(toml_path, 'r', encoding='utf-8') as f:
        config = f.read()

    # Parse dependencies from config
    deps = {}
    in_deps = False
    for line in config.split('\n'):
        if line.strip() == '[dependencies]':
            in_deps = True
            continue
        if line.startswith('[') and in_deps:
            in_deps = False
        if in_deps and '=' in line:
            key, val = line.split('=', 1)
            key = key.strip().strip('"')
            val = val.strip().strip('"')
            deps[key] = {'source': val, 'version': 'latest'}

    lock = {
        'version': 1,
        'updated': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'packages': deps,
    }

    with open(lock_path, 'w', encoding='utf-8') as f:
        json.dump(lock, f, indent=2)

    if deps:
        print(f'Lock file updated: {lock_path}')


def cmd_version(args) -> None:
    """Print version."""
    print(f'Iotift Compiler v{__version__}')


# ─────────────────────────────────────────
#  LEGACY CLI (backward compat)
# ─────────────────────────────────────────

def _build_legacy_parser() -> argparse.ArgumentParser:
    """Build the legacy argument parser (source file as positional arg)."""
    ap = argparse.ArgumentParser(
        description=f'Iotift Compiler v{__version__} — .iot → ESP32 C++',
    )
    ap.add_argument('source', help='input .iot source file')
    ap.add_argument('-o', '--output', default='generated.c',
                    help='output .c file (default: generated.c)')
    ap.add_argument('--ast', action='store_true',
                    help='dump AST to stdout and exit')
    ap.add_argument('--device', default='esp32',
                    help='target device (default: esp32)')
    ap.add_argument('--target', default=None,
                    help='target device alias (same as --device)')
    ap.add_argument('--baud', type=int, default=115200,
                    help='serial baud rate (default: 115200)')
    ap.add_argument('--project', action='store_true',
                    help='generate a PlatformIO project folder')
    ap.add_argument('--flash', action='store_true',
                    help='generate PlatformIO project, build, and upload')
    ap.add_argument('--port', default=None,
                    help='serial port for flashing (auto-detected if omitted)')
    ap.add_argument('--direct-codegen', action='store_true',
                    help='use direct AST→C codegen (skip IR pipeline)')
    ap.add_argument('--ir-dump', action='store_true',
                    help='dump IR to stdout (implies --no-optimize)')
    ap.add_argument('--no-optimize', action='store_true',
                    help='skip IR optimization passes')
    ap.add_argument('--Werror', action='store_true',
                    help='promote all warnings to errors')
    ap.add_argument('--Wno', action='append', default=[],
                    help='disable specific warning')
    ap.add_argument('--scheduler-slots', type=int, default=16,
                    help='number of scheduler task slots (default: 16)')
    ap.add_argument('--debug', action='store_true',
                    help='emit source maps and verbose output')
    ap.add_argument('--version', action='version',
                    version=f'Iotift Compiler v{__version__}')
    return ap


def _handle_legacy(args) -> None:
    """Handle legacy-style invocation (positional source file)."""
    # --ast flag
    if args.ast:
        source = _read_source(args.source)
        ast = _parse_source(source)
        from pprint import pprint
        pprint(ast)
        return

    # --project / --flash path
    if args.project or args.flash:
        pio_cmd = _ensure_platformio()
        if args.flash:
            _ensure_pyserial()
            if not args.port:
                args.port = _find_esp32_port()
                if args.port is None:
                    print('Error: no ESP32 detected. Connect your device or specify --port.')
                    sys.exit(1)

        source = _read_source(args.source)
        ast = _parse_source(source)
        ast = _resolve_imports(ast, args.source)

        result = _semantic_check(ast, werror=args.Werror,
                                 disabled_warnings=set(args.Wno))
        if result['errors']:
            for err in result['errors']:
                print(err, file=sys.stderr)
            sys.exit(1)
        if result['warnings']:
            for w in result['warnings']:
                print(w, file=sys.stderr)

        c_code, device_name, source_map = _generate_c(
            ast,
            device=args.target or args.device,
            baud=args.baud,
            scheduler_slots=args.scheduler_slots,
            direct_codegen=args.direct_codegen,
            no_optimize=args.no_optimize,
            ir_dump=args.ir_dump,
            debug=args.debug,
            source_path=os.path.abspath(args.source),
        )

        project_dir = _generate_platformio(args.source, c_code, args.baud)

        if args.flash:
            _flash_device(pio_cmd, project_dir, args.port)

        if source_map is not None:
            map_path = os.path.join(project_dir, 'src', 'main.cpp.map.json')
            with open(map_path, 'w', encoding='utf-8') as f:
                json.dump(source_map, f, indent=2)
            print(f'Source map written: {map_path}')
        return

    # Simple compilation (legacy default)
    source = _read_source(args.source)
    ast = _parse_source(source)
    ast = _resolve_imports(ast, args.source)

    result = _semantic_check(ast, werror=args.Werror,
                             disabled_warnings=set(args.Wno))
    if result['errors']:
        for err in result['errors']:
            print(err, file=sys.stderr)
        sys.exit(1)
    if result['warnings']:
        for w in result['warnings']:
            print(w, file=sys.stderr)

    c_code, device_name, source_map = _generate_c(
        ast,
        device=args.target or args.device,
        baud=args.baud,
        scheduler_slots=args.scheduler_slots,
        direct_codegen=args.direct_codegen,
        no_optimize=args.no_optimize,
        ir_dump=args.ir_dump,
        debug=args.debug,
        source_path=os.path.abspath(args.source),
    )

    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(c_code)

    print(f'Compiled {args.source} -> {args.output} (target: {device_name})')

    if source_map is not None:
        map_path = args.output + '.map.json'
        with open(map_path, 'w', encoding='utf-8') as f:
            json.dump(source_map, f, indent=2)
        print(f'Source map written: {map_path}')


# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────

def _build_subcommand_parser() -> argparse.ArgumentParser:
    """Build the subcommand-based argument parser."""
    ap = argparse.ArgumentParser(
        description=f'Iotift Compiler v{__version__} — embedded language toolchain',
    )
    ap.add_argument('--version', action='version',
                    version=f'Iotift Compiler v{__version__}')

    subs = ap.add_subparsers(dest='subcommand', title='commands')

    # ── check ──
    chk = subs.add_parser('check', help='type-check only, no code generation')
    chk.add_argument('source', help='input .iot source file')
    chk.add_argument('--Werror', action='store_true',
                     help='promote all warnings to errors')
    chk.add_argument('--Wno', action='append', default=[],
                     help='disable specific warning')

    # ── build ──
    bld = subs.add_parser('build', help='compile .iot to C')
    bld.add_argument('source', help='input .iot source file')
    bld.add_argument('-o', '--output', default=None,
                     help='output .c file (default: <source>.c)')
    bld.add_argument('--device', default='esp32',
                     help='target device (default: esp32)')
    bld.add_argument('--target', default=None,
                     help='target device alias (same as --device)')
    bld.add_argument('--baud', type=int, default=115200,
                     help='serial baud rate (default: 115200)')
    bld.add_argument('--direct-codegen', action='store_true',
                     help='use direct AST→C codegen (skip IR pipeline)')
    bld.add_argument('--ir-dump', action='store_true',
                     help='dump IR to stdout')
    bld.add_argument('--no-optimize', action='store_true',
                     help='skip IR optimization passes')
    bld.add_argument('--Werror', action='store_true',
                     help='promote all warnings to errors')
    bld.add_argument('--Wno', action='append', default=[],
                     help='disable specific warning')
    bld.add_argument('--scheduler-slots', type=int, default=16,
                     help='number of scheduler task slots (default: 16)')
    bld.add_argument('--debug', action='store_true',
                     help='emit source maps and verbose output')

    # ── flash ──
    fls = subs.add_parser('flash', help='compile and flash to device')
    fls.add_argument('source', help='input .iot source file')
    fls.add_argument('--device', default='esp32',
                     help='target device (default: esp32)')
    fls.add_argument('--target', default=None,
                     help='target device alias (same as --device)')
    fls.add_argument('--baud', type=int, default=115200,
                     help='serial baud rate (default: 115200)')
    fls.add_argument('--port', default=None,
                     help='serial port (auto-detected if omitted)')
    fls.add_argument('--direct-codegen', action='store_true',
                     help='use direct AST→C codegen (skip IR pipeline)')
    fls.add_argument('--no-optimize', action='store_true',
                     help='skip IR optimization passes')
    fls.add_argument('--Werror', action='store_true',
                     help='promote all warnings to errors')
    fls.add_argument('--Wno', action='append', default=[],
                     help='disable specific warning')
    fls.add_argument('--scheduler-slots', type=int, default=16,
                     help='number of scheduler task slots (default: 16)')
    fls.add_argument('--debug', action='store_true',
                     help='emit source maps and verbose output')

    # ── fmt ──
    fmt = subs.add_parser('fmt', help='format source file')
    fmt.add_argument('source', help='input .iot source file')
    fmt.add_argument('--check', action='store_true',
                     help='check formatting without modifying file')

    # ── lint ──
    lint = subs.add_parser('lint', help='run linter')
    lint.add_argument('source', help='input .iot source file')

    # ── new ──
    new = subs.add_parser('new', help='scaffold a new project')
    new.add_argument('name', help='project name')

    # ── lsp ──
    lsp = subs.add_parser('lsp', help='start language server (for editor integration)')

    # ── debug ──
    dbg = subs.add_parser('debug', help='build with debug flags and launch GDB')
    dbg.add_argument('source', help='input .iot source file')
    dbg.add_argument('--device', default='esp32',
                     help='target device (default: esp32)')
    dbg.add_argument('--target', default=None,
                     help='target device alias (same as --device)')
    dbg.add_argument('--port', default=None,
                     help='serial port for OpenOCD/GDB (auto-detected if omitted)')
    dbg.add_argument('--gdb', default='arm-none-eabi-gdb',
                     help='path to GDB executable')
    dbg.add_argument('--no-flash', action='store_true',
                     help='skip flashing, just build and launch debugger')

    # ── add ──
    add_pkg = subs.add_parser('add', help='add a package dependency')
    add_pkg.add_argument('package', help='package specifier (e.g. github.com/user/package)')
    add_pkg.add_argument('--version', default=None,
                         help='pin to a specific version tag')

    # ── remove ──
    rm_pkg = subs.add_parser('remove', help='remove a package dependency')
    rm_pkg.add_argument('package', help='package name to remove')

    # ── update ──
    up_pkg = subs.add_parser('update', help='update package dependencies')
    up_pkg.add_argument('package', nargs='?', default=None,
                        help='specific package to update (omit for all)')

    # ── version ──
    ver = subs.add_parser('version', help='print version')

    return ap


def main() -> None:
    # ── Detect legacy vs subcommand mode ──
    # If first arg is a .iot file, use legacy parser
    if len(sys.argv) > 1 and sys.argv[1].endswith('.iot'):
        ap = _build_legacy_parser()
        args = ap.parse_args()
        _handle_legacy(args)
        return

    # ── Check for subcommand ──
    subcommands = {'check', 'build', 'flash', 'fmt', 'lint', 'lsp', 'new', 'version',
                    'debug', 'add', 'remove', 'update'}
    has_subcommand = any(arg in subcommands for arg in sys.argv[1:3])

    if has_subcommand:
        ap = _build_subcommand_parser()
        args = ap.parse_args()

        if args.subcommand is None:
            ap.print_help()
            sys.exit(1)

        # Dispatch
        handlers = {
            'check': cmd_check,
            'build': cmd_build,
            'flash': cmd_flash,
            'fmt': cmd_fmt,
            'lint': cmd_lint,
            'lsp': cmd_lsp,
            'new': cmd_new,
            'debug': cmd_debug,
            'add': cmd_add,
            'remove': cmd_remove,
            'update': cmd_update,
            'version': cmd_version,
        }

        handler = handlers.get(args.subcommand)
        if handler:
            # Set default output for build command
            if args.subcommand == 'build' and not getattr(args, 'output', None):
                base = os.path.splitext(os.path.basename(args.source))[0]
                args.output = base + '.c'
            handler(args)
        else:
            ap.print_help()
            sys.exit(1)
    else:
        # No subcommand, no .iot file — show help
        ap = _build_subcommand_parser()
        ap.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
