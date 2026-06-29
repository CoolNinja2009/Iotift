# Iotift

Iotift is an embedded programming language.

## Style

- Never break backwards compatibility.
- Target ESP32 first.
- Backend generates C.
- Scheduler is fully non-blocking.
- Prefer generated code over runtime magic.

## Compiler pipeline

Lexer
Parser
AST
Semantic Analysis
Optimizer
C Generator

## Naming

Generated functions begin with _iotift_.