#!/usr/bin/env python3
"""
IOTIFT Compiler
Usage: python iotift.py <source.iot> [-o output.c] [--ast]
"""

import sys
import argparse
from lexer   import tokenize, LexError
from parser  import Parser, ParseError
from codegen import CodeGen


def main():
    ap = argparse.ArgumentParser(description='IOTIFT compiler')
    ap.add_argument('source',          help='input .iot source file')
    ap.add_argument('-o', '--output',  help='output .c file (default: generated.c)', default='generated.c')
    ap.add_argument('--ast',           help='dump AST to stdout', action='store_true')
    ap.add_argument('--device',        help='target device (default: arduino_uno)', default='arduino_uno')
    args = ap.parse_args()

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

    # ── write output ──
    with open(args.output, 'w') as f:
        f.write(c_code)

    print(f"✓ compiled {args.source}  →  {args.output}  (target: {gen.device})")


if __name__ == '__main__':
    main()
