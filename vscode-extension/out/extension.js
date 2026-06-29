"use strict";
/**
 * Iotift VS Code Extension
 *
 * Provides language support for .iot files:
 * - Syntax highlighting (TextMate grammar)
 * - Language server protocol (diagnostics, completion, hover, etc.)
 * - Snippets
 * - Build/flash/format/lint commands
 */
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = __importStar(require("vscode"));
const node_1 = require("vscode-languageclient/node");
let client;
/**
 * Activate the extension.
 */
function activate(context) {
    console.log('Iotift extension activated');
    // ── Register commands ──────────────────────────
    // Compile to C
    context.subscriptions.push(vscode.commands.registerCommand('iotift.compile', async () => {
        const editor = vscode.window.activeTextEditor;
        if (!editor || !editor.document.fileName.endsWith('.iot')) {
            vscode.window.showWarningMessage('Open a .iot file to compile.');
            return;
        }
        const document = editor.document;
        await document.save();
        const outputPath = document.fileName.replace(/\.iot$/, '.c');
        const result = await runIotift([
            'build',
            document.fileName,
            '-o', outputPath,
        ]);
        if (result.success) {
            vscode.window.showInformationMessage(`Compiled: ${outputPath}`);
        }
        else {
            vscode.window.showErrorMessage(`Compilation failed:\n${result.stderr || result.stdout}`);
        }
    }));
    // Compile and flash
    context.subscriptions.push(vscode.commands.registerCommand('iotift.flash', async () => {
        const editor = vscode.window.activeTextEditor;
        if (!editor || !editor.document.fileName.endsWith('.iot')) {
            vscode.window.showWarningMessage('Open a .iot file to flash.');
            return;
        }
        const document = editor.document;
        await document.save();
        const config = vscode.workspace.getConfiguration('iotift');
        const port = config.get('flashPort', '');
        const args = ['flash', document.fileName];
        if (port) {
            args.push('--port', port);
        }
        vscode.window.showInformationMessage('Building and flashing...');
        const result = await runIotift(args);
        if (result.success) {
            vscode.window.showInformationMessage('Flash complete!');
        }
        else {
            vscode.window.showErrorMessage(`Flash failed:\n${result.stderr || result.stdout}`);
        }
    }));
    // Format document
    context.subscriptions.push(vscode.commands.registerCommand('iotift.format', async () => {
        const editor = vscode.window.activeTextEditor;
        if (!editor || !editor.document.fileName.endsWith('.iot')) {
            vscode.window.showWarningMessage('Open a .iot file to format.');
            return;
        }
        const document = editor.document;
        await document.save();
        const result = await runIotift(['fmt', document.fileName]);
        if (result.success) {
            vscode.window.showInformationMessage('Formatted.');
            // Reload the file to show changes
            const doc = await vscode.workspace.openTextDocument(document.fileName);
            await vscode.window.showTextDocument(doc);
        }
        else {
            vscode.window.showErrorMessage(`Format failed:\n${result.stderr || result.stdout}`);
        }
    }));
    // Lint document
    context.subscriptions.push(vscode.commands.registerCommand('iotift.lint', async () => {
        const editor = vscode.window.activeTextEditor;
        if (!editor || !editor.document.fileName.endsWith('.iot')) {
            vscode.window.showWarningMessage('Open a .iot file to lint.');
            return;
        }
        const document = editor.document;
        await document.save();
        const result = await runIotift(['lint', document.fileName]);
        if (result.success) {
            vscode.window.showInformationMessage(result.stdout.trim() || 'No issues found.');
        }
        else {
            // Lint exits 1 on errors — still show output
            vscode.window.showWarningMessage(result.stdout.trim() || result.stderr || 'Lint found issues.');
        }
    }));
    // Restart language server
    context.subscriptions.push(vscode.commands.registerCommand('iotift.restartServer', async () => {
        if (client) {
            await client.restart();
            vscode.window.showInformationMessage('Iotift language server restarted.');
        }
    }));
    // ── Start language server ──────────────────────
    startLanguageServer(context);
}
/**
 * Start the LSP client.
 */
function startLanguageServer(context) {
    const config = vscode.workspace.getConfiguration('iotift');
    // Determine server path
    let serverPath = config.get('serverPath', '');
    if (!serverPath) {
        serverPath = 'iotift';
    }
    const serverExecutable = {
        command: serverPath,
        args: ['lsp'],
    };
    const serverOptions = {
        run: serverExecutable,
        debug: {
            ...serverExecutable,
            options: { env: { ...process.env } },
        },
    };
    const clientOptions = {
        documentSelector: [
            { scheme: 'file', language: 'iotift' },
        ],
        synchronize: {
            fileEvents: vscode.workspace.createFileSystemWatcher('**/*.iot'),
        },
        outputChannelName: 'Iotift Language Server',
        traceOutputChannel: vscode.window.createOutputChannel('Iotift Language Server Trace'),
    };
    client = new node_1.LanguageClient('iotift-lsp', 'Iotift Language Server', serverOptions, clientOptions);
    // Set trace level from configuration
    // Trace values: 0=Off, 1=Messages, 2=Verbose
    const traceLevel = config.get('trace.server', 'off');
    if (traceLevel === 'verbose') {
        client.setTrace(2);
    }
    else if (traceLevel === 'messages') {
        client.setTrace(1);
    }
    // Start the client and register it for disposal
    client.start().then(() => {
        console.log('Iotift language server ready');
    }).catch((err) => {
        console.error('Iotift language server failed to start:', err.message);
    });
    // Push the client itself as the disposable (it implements Disposable)
    context.subscriptions.push(client);
}
/**
 * Deactivate the extension.
 */
function deactivate() {
    if (client) {
        return client.stop();
    }
    return undefined;
}
/**
 * Run an Iotift CLI command.
 */
async function runIotift(args) {
    const config = vscode.workspace.getConfiguration('iotift');
    const serverPath = config.get('serverPath', '') || 'iotift';
    return new Promise((resolve) => {
        const cp = require('child_process');
        cp.execFile(serverPath, args, { maxBuffer: 10 * 1024 * 1024 }, (error, stdout, stderr) => {
            resolve({
                success: !error,
                stdout,
                stderr,
            });
        });
    });
}
//# sourceMappingURL=extension.js.map