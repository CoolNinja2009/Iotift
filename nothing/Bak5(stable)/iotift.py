#!/usr/bin/env python3
"""
IOTIFT Compiler
Usage: python iotift.py <source.iot> [-o output.c] [--ast]
"""

import sys
import argparse
import os
import shutil
import subprocess
import site
from lexer   import tokenize, LexError
from parser  import Parser, ParseError
from codegen_fixed import CodeGen


def main():
    ap = argparse.ArgumentParser(description='IOTIFT compiler')
    ap.add_argument('source',          help='input .iot source file')
    ap.add_argument('-o', '--output',  help='output .c file (default: generated.c)', default='generated.c')
    ap.add_argument('--ast',           help='dump AST to stdout', action='store_true')
    ap.add_argument('--device',        help='target device (default: esp32)', default='esp32')
    ap.add_argument('--project',       help='generate PlatformIO project folder', action='store_true')
    ap.add_argument('--flash',         help='generate project, build and upload', action='store_true')
    ap.add_argument('--port',          help='serial port for flashing (required with --flash)')
    args = ap.parse_args()

    if args.flash and not args.port:
        print("Error: --port is required when using --flash")
        sys.exit(1)

    if args.project or args.flash:
        try:
            import platformio
            pio_available = True
        except ImportError:
            pio_available = False
        
        if not pio_available:
            print("PlatformIO not found. Installing...")
            result = subprocess.run([sys.executable, "-m", "pip", "install", "platformio"])
            if result.returncode != 0:
                print("Error: Failed to install PlatformIO")
                sys.exit(1)
            print("✓ PlatformIO installed")
        
        # Get pio command path
        scripts_path = os.path.join(os.path.dirname(site.getusersitepackages()), "Scripts")
        pio_cmd = os.path.join(scripts_path, "pio.exe")

    # ── read source ──
    try:
        with open(args.source) as f:
            source = f.read()
    except FileNotFoundError:
        print(f"Error: file not found: {args.source}")
        sys.exit(1)

    # ── lex ──
    try:
        tokens = tokenize(source)
    except LexError as e:
        print(f"Lex error: {e}")
        sys.exit(1)

    # ── parse ──
    try:
        parser = Parser(tokens)
        ast    = parser.parse()
    except ParseError as e:
        print(f"Parse error: {e}")
        sys.exit(1)

    # ── dump AST (optional) ──
    if args.ast:
        import pprint
        pprint.pprint(ast)
        return

    # ── codegen ──
    gen = CodeGen(device=args.device)
    c_code = gen.generate(ast)

    # ── generate PlatformIO project if requested ──
    if args.project or args.flash:
        base_name = os.path.splitext(os.path.basename(args.source))[0]
        project_name = base_name + "_project"
        project_dir = os.path.join(os.getcwd(), project_name)
        print(f"Generating PlatformIO project: {project_dir}")
        os.makedirs(project_dir, exist_ok=True)
        os.makedirs(os.path.join(project_dir, "src"), exist_ok=True)
        os.makedirs(os.path.join(project_dir, "include"), exist_ok=True)

        # platformio.ini
        ini_content = """[env:esp32]
platform = espressif32
board = esp32dev
framework = arduino
monitor_speed = 115200
build_flags = -O2
"""
        with open(os.path.join(project_dir, "platformio.ini"), 'w', encoding='utf-8') as f:
            f.write(ini_content)

        # src/main.c
        with open(os.path.join(project_dir, "src", "main.cpp"), 'w', encoding='utf-8') as f:
            f.write(c_code)

        print(f"✓ generated PlatformIO project: {project_dir}")

    # ── flash if requested ──
    if args.flash:
        print(f"Building and flashing to {args.port}...")
        original_cwd = os.getcwd()
        os.chdir(project_dir)
        result = subprocess.run([pio_cmd, "run", "--target", "upload", "--upload-port", args.port])
        os.chdir(original_cwd)
        if result.returncode == 0:
            print("✓ flashed to device")
        else:
            print("Error: flashing failed")
            sys.exit(1)

    # ── write output file if not project mode ──
    if not args.project and not args.flash:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(c_code)

        print(f"✓ compiled {args.source}  →  {args.output}  (target: {gen.device})")


if __name__ == '__main__':
    main()
