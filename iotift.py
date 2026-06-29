#!/usr/bin/env python3
"""
Iotift Compiler — CLI entry point.

Usage:
    python iotift.py <source.iot> [-o output.c] [--ast] [--flash] [--project]
"""

from __future__ import annotations

import sys
import os
import argparse
import subprocess
import site
from typing import Optional

from lexer    import tokenize, LexError
from parser   import Parser, ParseError
from semantic import SemanticAnalyzer
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
    bridge manufacturers.  Returns the device path of the first match,
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
        print('PlatformIO not found.  Installing …')
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
        print('pyserial not found.  Installing …')
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', 'pyserial'],
        )
        if result.returncode != 0:
            print('Error: failed to install pyserial')
            sys.exit(1)
        print('pyserial installed.')


# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description=f'Iotift Compiler v{__version__}  —  .iot → ESP32 C++',
    )
    ap.add_argument(
        'source', help='input .iot source file',
    )
    ap.add_argument(
        '-o', '--output', default='generated.c',
        help='output .c file (default: generated.c)',
    )
    ap.add_argument(
        '--ast', action='store_true',
        help='dump AST to stdout and exit',
    )
    ap.add_argument(
        '--device', default='esp32',
        help='target device (default: esp32)',
    )
    ap.add_argument(
        '--baud', type=int, default=115200,
        help='serial baud rate for generated setup() (default: 115200)',
    )
    ap.add_argument(
        '--project', action='store_true',
        help='generate a PlatformIO project folder',
    )
    ap.add_argument(
        '--flash', action='store_true',
        help='generate PlatformIO project, build, and upload',
    )
    ap.add_argument(
        '--port', default=None,
        help='serial port for flashing (auto-detected if omitted)',
    )
    ap.add_argument(
        '--direct-codegen', action='store_true',
        help='use direct AST→C codegen (skip IR pipeline)',
    )
    ap.add_argument(
        '--ir-dump', action='store_true',
        help='dump IR to stdout (implies --no-optimize)',
    )
    ap.add_argument(
        '--no-optimize', action='store_true',
        help='skip IR optimization passes',
    )
    ap.add_argument(
        '--Werror', action='store_true',
        help='promote all warnings to errors',
    )
    ap.add_argument(
        '--Wno', action='append', default=[],
        help='disable specific warning (unused-variable, unused-function, '
             'used-before-init, implicit-narrowing, empty-body, void-loop-deprecated)',
    )
    ap.add_argument(
        '--scheduler-slots', type=int, default=16,
        help='number of scheduler task slots (default: 16)',
    )
    ap.add_argument(
        '--version', action='version',
        version=f'Iotift Compiler v{__version__}',
    )
    args = ap.parse_args()

    # ── pre-flight: PlatformIO / pyserial ──
    pio_cmd: Optional[str] = None
    if args.project or args.flash:
        pio_cmd = _ensure_platformio()

    if args.flash:
        _ensure_pyserial()
        if not args.port:
            args.port = _find_esp32_port()
            if args.port is None:
                print(
                    'Error: no ESP32 detected.  '
                    'Connect your device or specify --port.'
                )
                sys.exit(1)

    # ── read source ──
    try:
        with open(args.source, encoding='utf-8') as f:
            source = f.read()
    except FileNotFoundError:
        print(f'Error: file not found — {args.source}')
        sys.exit(1)

    # ── lex ──
    try:
        tokens = tokenize(source)
    except LexError as e:
        print(f'Lex error: {e}')
        sys.exit(1)

    # ── parse ──
    try:
        parser = Parser(tokens)
        ast    = parser.parse()
    except ParseError as e:
        print(f'Parse error: {e}')
        sys.exit(1)

    # ── dump AST (optional) ──
    if args.ast:
        from pprint import pprint
        pprint(ast)
        return

    # ── semantic analysis ──
    analyzer = SemanticAnalyzer(
        werror=args.Werror,
        disabled_warnings=set(args.Wno),
    )
    analyzer.analyze(ast)

    if analyzer.has_errors():
        for err in analyzer.errors():
            print(err, file=sys.stderr)
        sys.exit(1)

    if analyzer.warnings():
        for w in analyzer.warnings():
            print(w, file=sys.stderr)

    # ── codegen ──
    if args.direct_codegen:
        # Legacy path: AST → C directly
        gen    = CodeGen(device=args.device, baud_rate=args.baud,
                         scheduler_slots=args.scheduler_slots)
        c_code = gen.generate(ast)
        device_name = gen._device
    else:
        # IR pipeline: AST → IR → optimize → C
        lowering  = IRLowering(scheduler_slots=args.scheduler_slots)
        ir_module = lowering.lower(ast)

        if not args.no_optimize:
            optimizer = IROptimizer(ir_module)
            ir_module = optimizer.run_all()

        if args.ir_dump:
            from pprint import pprint
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

        ir_gen = IRCodeGen(device=args.device, baud_rate=args.baud,
                           scheduler_slots=args.scheduler_slots)
        c_code = ir_gen.generate(ir_module)
        device_name = args.device

    # ── PlatformIO project generation ──
    if args.project or args.flash:
        base_name    = os.path.splitext(os.path.basename(args.source))[0]
        project_dir  = os.path.join(os.getcwd(), base_name + '_project')

        print(f'Generating PlatformIO project: {project_dir}')
        os.makedirs(project_dir, exist_ok=True)
        os.makedirs(os.path.join(project_dir, 'src'), exist_ok=True)
        os.makedirs(os.path.join(project_dir, 'include'), exist_ok=True)

        ini = (
            '[env:esp32]\n'
            'platform = espressif32\n'
            'board = esp32dev\n'
            'framework = arduino\n'
            f'monitor_speed = {args.baud}\n'
            'build_flags = -O2\n'
        )
        with open(os.path.join(project_dir, 'platformio.ini'), 'w', encoding='utf-8') as f:
            f.write(ini)

        with open(os.path.join(project_dir, 'src', 'main.cpp'), 'w', encoding='utf-8') as f:
            f.write(c_code)

        print(f'PlatformIO project ready: {project_dir}')

    # ── flash ──
    if args.flash:
        assert pio_cmd is not None
        print(f'Building and flashing to {args.port} …')
        cwd = os.getcwd()
        try:
            os.chdir(project_dir)
            result = subprocess.run([
                pio_cmd, 'run', '--target', 'upload',
                '--upload-port', args.port,
            ])
        finally:
            os.chdir(cwd)

        if result.returncode == 0:
            print('Flashing complete.')
        else:
            print('Error: flashing failed.')
            sys.exit(1)

    # ── write output (non-project mode) ──
    if not args.project and not args.flash:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(c_code)
        print(
            f'Compiled {args.source}  ->  {args.output}  '
            f'(target: {device_name})'
        )


if __name__ == '__main__':
    main()
