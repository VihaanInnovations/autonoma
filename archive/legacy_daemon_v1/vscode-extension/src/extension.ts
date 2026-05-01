import * as vscode from 'vscode';
import * as cp from 'child_process';
import { getConfig, initSecrets } from './config';
import { ReviewerClient } from './client';
import { DiagnosticsManager } from './diagnostics';
import { registerCommands } from './commands';
import { LocalAIFixProvider, registerFixCommand } from './fixProvider';

let client: ReviewerClient;
let diagnosticsManager: DiagnosticsManager;
let myStatusBarItem: vscode.StatusBarItem | undefined;

export function activate(context: vscode.ExtensionContext) {
    console.log('Autonoma AI Engine extension is now active!');

    // Initialize Components
    initSecrets(context);
    const config = getConfig();
    client = new ReviewerClient(config);
    diagnosticsManager = new DiagnosticsManager();

    // Check Daemon Health
    client.checkDaemonHealth().then(async isHealthy => {
        if (!isHealthy) {
            const selection = await vscode.window.showWarningMessage(
                'Autonoma daemon is not running.',
                'Start Daemon',
                'Open Troubleshooting'
            );

            if (selection === 'Start Daemon') {
                try {
                    vscode.window.setStatusBarMessage('Starting Autonoma Daemon...', 5000);
                    // Try systemd start
                    cp.exec('systemctl --user start autonoma', (err, stdout, stderr) => {
                        if (err) {
                            // Fallback or show error
                            vscode.window.showErrorMessage(`Failed to start daemon: ${stderr || err.message}. Ensure Docker container is running.`);
                            vscode.env.openExternal(vscode.Uri.parse('https://github.com/autonoma-ai/autonoma-ai.github.io#troubleshooting'));
                        } else {
                            vscode.window.showInformationMessage('Daemon started successfully.');
                            // Retry connectivity ?
                        }
                    });
                } catch (e) {
                    vscode.window.showErrorMessage(`Error starting daemon: ${e}`);
                }
            } else if (selection === 'Open Troubleshooting') {
                vscode.env.openExternal(vscode.Uri.parse('https://github.com/autonoma-ai/autonoma-ai.github.io#troubleshooting'));
            }
        }
    });

    // Register Commands
    registerCommands(context, client, diagnosticsManager);

    // Register Fix Provider
    registerFixCommand(context, config);
    context.subscriptions.push(
        vscode.languages.registerCodeActionsProvider(
            { scheme: 'file' },
            new LocalAIFixProvider(config),
            { providedCodeActionKinds: [vscode.CodeActionKind.QuickFix] }
        )
    );

    // Event Listeners

    // 1. On Save (with streaming for instant feedback)
    context.subscriptions.push(
        vscode.workspace.onDidSaveTextDocument(async (document) => {
            if (shouldAnalyze(document)) {
                // Clear existing diagnostics
                diagnosticsManager.clearDiagnostics(document);

                // Use streaming for real-time feedback
                const issues: any[] = [];
                let statusMessage: vscode.Disposable | undefined;

                await client.analyzeFileStream(
                    document.fileName,
                    document.getText(),
                    "default_project",
                    (event) => {
                        if (event.type === 'issue' && event.issue) {
                            issues.push(event.issue);
                            // Add issue immediately for instant feedback
                            diagnosticsManager.addDiagnostic(document, event.issue);
                        } else if (event.type === 'status' && event.message) {
                            // Update status bar item
                            if (myStatusBarItem) {
                                myStatusBarItem.text = `$(sync~spin) Autonoma: ${event.message}`;
                                myStatusBarItem.tooltip = "Autonoma is analyzing your code...";
                                myStatusBarItem.show();
                            }
                        } else if (event.type === 'complete') {
                            // Final update
                            if (statusMessage) {
                                statusMessage.dispose();
                            }
                            const count = event.total_issues || issues.length;
                            vscode.window.setStatusBarMessage(
                                `Autonoma: Analysis complete. Found ${count} issue${count !== 1 ? 's' : ''}.`,
                                3000
                            );
                        } else if (event.type === 'error') {
                            // Show error
                            if (statusMessage) {
                                statusMessage.dispose();
                            }
                            vscode.window.showErrorMessage(
                                `Autonoma Error: ${event.message || 'Unknown error'}`
                            );
                        }
                    }
                );
            }
        })
    );

    // 2. On Open
    context.subscriptions.push(
        vscode.workspace.onDidOpenTextDocument(async (document) => {
            if (shouldAnalyze(document)) {
                // Optional: Analyze on open
                // const issues = await client.analyzeFile(document.fileName, document.getText(), "default_project");
                // diagnosticsManager.updateDiagnostics(document, issues);
            }
        })
    );

    // 3. Configuration Change
    context.subscriptions.push(
        vscode.workspace.onDidChangeConfiguration((e) => {
            if (e.affectsConfiguration('autonoma')) {
                // Refresh config
                const newConfig = getConfig();
                client = new ReviewerClient(newConfig);
                vscode.window.showInformationMessage('Autonoma configuration updated.');
            }
        })
    );
}

function shouldAnalyze(document: vscode.TextDocument): boolean {
    return (
        document.uri.scheme === 'file' &&
        !document.fileName.includes("node_modules") &&
        !document.fileName.includes(".git")
    );
}

export function deactivate() {
    // Cleanup if needed
}
