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
from codegen import CodeGen


def find_esp32_port():
    from serial.tools import list_ports
    """
    Auto-detect ESP32 serial port by checking common USB-serial chips.
    Returns port.device of first match or None.
    """
    ports = list_ports.comports()
    keywords = ['CP210x', 'CH340', 'CH341', 'FTDI', 'Silicon Labs']
    matching_ports = []
    
    for port in ports:
        desc_upper = (port.description or '').upper()
        manuf_upper = (port.manufacturer or '').upper()
        for kw in keywords:
            if kw.upper() in desc_upper or kw.upper() in manuf_upper:
                matching_ports.append(port)
                break
    
    if not matching_ports:
        return None
    
    selected_port = matching_ports[0]
    port_name = selected_port.device
    if len(matching_ports) > 1:
        print(f"✓ Multiple ESP32 devices found, using {port_name}")
    else:
        print(f"✓ ESP32 found on {port_name}")
    return port_name


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
        
        # Auto-install pyserial for port detection
        try:
            from serial.tools import list_ports
            SERIAL_AVAILABLE = True
        except ImportError:
            SERIAL_AVAILABLE = False
        
        if args.flash and not SERIAL_AVAILABLE:
            print("pyserial not found, installing...")
            result = subprocess.run([sys.executable, "-m", "pip", "install", "pyserial"])
            if result.returncode != 0:
                print("Error: Failed to install pyserial")
                sys.exit(1)
            print("✓ pyserial installed")
            SERIAL_AVAILABLE = True
        
        if args.flash:
            if not args.port:
                port = find_esp32_port()
                if port is None:
                    print("Error: No ESP32 found. Connect your ESP32 or specify port with --port")
                    sys.exit(1)
                args.port = port
            # Prints handled in find_esp32_port()
        
        scripts_path = os.path.join(os.path.dirname(site.getusersitepackages()), "Scripts")
        pio_cmd = os.path.join(scripts_path, "pio.exe")

    # ── read source ──
    try:
        with open(args.source, encoding='utf-8') as f:
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

        ini_content = """[env:esp32]
platform = espressif32
board = esp32dev
framework = arduino
monitor_speed = 115200
build_flags = -O2
"""
        with open(os.path.join(project_dir, "platformio.ini"), 'w', encoding='utf-8') as f:
            f.write(ini_content)

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