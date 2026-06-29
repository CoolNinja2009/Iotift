# Iotift for VS Code

VS Code extension for the [Iotift](https://github.com/iotift/iotift) embedded programming language.

## Features

- **Syntax highlighting** — full TextMate grammar for `.iot` files
- **Diagnostics** — real-time error and warning reporting as you type
- **Code completion** — keywords, types, snippets, and in-scope symbols
- **Hover** — type information and documentation on hover
- **Go to Definition** — jump to symbol declarations
- **Find References** — find all uses of a symbol
- **Document Symbols** — outline view for `.iot` files
- **Snippets** — ready-made templates for common constructs

## Commands

| Command | Description |
|---------|-------------|
| `Iotift: Compile to C` | Compile the current `.iot` file to C |
| `Iotift: Compile and Flash` | Compile and flash to device |
| `Iotift: Format Document` | Format the current document |
| `Iotift: Lint Document` | Run the linter |
| `Iotift: Restart Language Server` | Restart the LSP server |

## Requirements

- **Iotift CLI** installed and available on your `PATH`
- Or set `iotift.serverPath` to the full path of the `iotift` executable

## Extension Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `iotift.serverPath` | `""` | Path to iotift executable |
| `iotift.targetDevice` | `"esp32"` | Target device for compilation |
| `iotift.baudRate` | `115200` | Serial baud rate |
| `iotift.schedulerSlots` | `16` | Number of scheduler slots |
| `iotift.trace.server` | `"off"` | LSP trace level |

## Snippets

Type one of these prefixes and press Tab:

- `pin` — Pin declaration
- `fn` — Function
- `every` — Repeating timer
- `on_event` — Pin event handler
- `struct` — Struct definition
- `enum` — Enum definition
- `if` / `if_else` — Conditionals
- `for` / `while` / `loop` — Loops
- ...and many more

## Building from source

```bash
cd vscode-extension
npm install
npm run compile
```

Then press F5 to launch the extension in a new VS Code window.
