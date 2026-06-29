/**
 * Iotift VS Code Extension
 *
 * Provides language support for .iot files:
 * - Syntax highlighting (TextMate grammar)
 * - Language server protocol (diagnostics, completion, hover, etc.)
 * - Snippets
 * - Build/flash/format/lint commands
 */

import * as vscode from 'vscode';
import {
    LanguageClient,
    LanguageClientOptions,
    ServerOptions,
    Executable,
} from 'vscode-languageclient/node';

let client: LanguageClient | undefined;

/**
 * Activate the extension.
 */
export function activate(context: vscode.ExtensionContext): void {
    console.log('Iotift extension activated');

    // ── Register commands ──────────────────────────

    // Compile to C
    context.subscriptions.push(
        vscode.commands.registerCommand('iotift.compile', async () => {
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
                vscode.window.showInformationMessage(
                    `Compiled: ${outputPath}`
                );
            } else {
                vscode.window.showErrorMessage(
                    `Compilation failed:\n${result.stderr || result.stdout}`
                );
            }
        })
    );

    // Compile and flash
    context.subscriptions.push(
        vscode.commands.registerCommand('iotift.flash', async () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor || !editor.document.fileName.endsWith('.iot')) {
                vscode.window.showWarningMessage('Open a .iot file to flash.');
                return;
            }

            const document = editor.document;
            await document.save();

            const config = vscode.workspace.getConfiguration('iotift');
            const port = config.get<string>('flashPort', '');

            const args = ['flash', document.fileName];
            if (port) {
                args.push('--port', port);
            }

            vscode.window.showInformationMessage('Building and flashing...');
            const result = await runIotift(args);

            if (result.success) {
                vscode.window.showInformationMessage('Flash complete!');
            } else {
                vscode.window.showErrorMessage(
                    `Flash failed:\n${result.stderr || result.stdout}`
                );
            }
        })
    );

    // Format document
    context.subscriptions.push(
        vscode.commands.registerCommand('iotift.format', async () => {
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
                const doc = await vscode.workspace.openTextDocument(
                    document.fileName
                );
                await vscode.window.showTextDocument(doc);
            } else {
                vscode.window.showErrorMessage(
                    `Format failed:\n${result.stderr || result.stdout}`
                );
            }
        })
    );

    // Lint document
    context.subscriptions.push(
        vscode.commands.registerCommand('iotift.lint', async () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor || !editor.document.fileName.endsWith('.iot')) {
                vscode.window.showWarningMessage('Open a .iot file to lint.');
                return;
            }

            const document = editor.document;
            await document.save();

            const result = await runIotift(['lint', document.fileName]);

            if (result.success) {
                vscode.window.showInformationMessage(
                    result.stdout.trim() || 'No issues found.'
                );
            } else {
                // Lint exits 1 on errors — still show output
                vscode.window.showWarningMessage(
                    result.stdout.trim() || result.stderr || 'Lint found issues.'
                );
            }
        })
    );

    // Restart language server
    context.subscriptions.push(
        vscode.commands.registerCommand('iotift.restartServer', async () => {
            if (client) {
                await client.restart();
                vscode.window.showInformationMessage(
                    'Iotift language server restarted.'
                );
            }
        })
    );

    // ── Start language server ──────────────────────

    startLanguageServer(context);
}

/**
 * Start the LSP client.
 */
function startLanguageServer(context: vscode.ExtensionContext): void {
    const config = vscode.workspace.getConfiguration('iotift');

    // Determine server path
    let serverPath = config.get<string>('serverPath', '');
    if (!serverPath) {
        serverPath = 'iotift';
    }

    const serverExecutable: Executable = {
        command: serverPath,
        args: ['lsp'],
    };

    const serverOptions: ServerOptions = {
        run: serverExecutable,
        debug: {
            ...serverExecutable,
            options: { env: { ...process.env } },
        },
    };

    const clientOptions: LanguageClientOptions = {
        documentSelector: [
            { scheme: 'file', language: 'iotift' },
        ],
        synchronize: {
            fileEvents: vscode.workspace.createFileSystemWatcher('**/*.iot'),
        },
        outputChannelName: 'Iotift Language Server',
        traceOutputChannel: vscode.window.createOutputChannel(
            'Iotift Language Server Trace'
        ),
    };

    client = new LanguageClient(
        'iotift-lsp',
        'Iotift Language Server',
        serverOptions,
        clientOptions
    );

    // Set trace level from configuration
    // Trace values: 0=Off, 1=Messages, 2=Verbose
    const traceLevel = config.get<string>('trace.server', 'off');
    if (traceLevel === 'verbose') {
        (client as any).setTrace(2);
    } else if (traceLevel === 'messages') {
        (client as any).setTrace(1);
    }

    // Start the client and register it for disposal
    client.start().then(() => {
        console.log('Iotift language server ready');
    }).catch((err: Error) => {
        console.error('Iotift language server failed to start:', err.message);
    });

    // Push the client itself as the disposable (it implements Disposable)
    context.subscriptions.push(client);
}

/**
 * Deactivate the extension.
 */
export function deactivate(): Promise<void> | undefined {
    if (client) {
        return client.stop();
    }
    return undefined;
}

/**
 * Run an Iotift CLI command.
 */
async function runIotift(
    args: string[]
): Promise<{ success: boolean; stdout: string; stderr: string }> {
    const config = vscode.workspace.getConfiguration('iotift');
    const serverPath = config.get<string>('serverPath', '') || 'iotift';

    return new Promise((resolve) => {
        const cp = require('child_process');
        cp.execFile(
            serverPath,
            args,
            { maxBuffer: 10 * 1024 * 1024 },
            (error: Error | null, stdout: string, stderr: string) => {
                resolve({
                    success: !error,
                    stdout,
                    stderr,
                });
            }
        );
    });
}
