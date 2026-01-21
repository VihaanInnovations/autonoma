import * as vscode from 'vscode';
import { ReviewerClient } from './client';
import { DiagnosticsManager } from './diagnostics';
import { SummaryPanel } from './ui/summaryPanel';

export function registerCommands(context: vscode.ExtensionContext, client: ReviewerClient, diagnostics: DiagnosticsManager) {
    const analyzeCommand = vscode.commands.registerCommand('hybrid-reviewer.analyze', async () => {
        const editor = vscode.window.activeTextEditor;
        if (!editor) {
            vscode.window.showInformationMessage('No active editor found.');
            return;
        }

        const document = editor.document;
        // Basic check to avoid analyzing huge files or binary
        if (document.lineCount > 5000) {
            // maybe warn?
        }

        // Clear existing diagnostics
        diagnostics.clearDiagnostics(document);

        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: "Analyzing file...",
            cancellable: false
        }, async (progress) => {
            const issues: any[] = [];
            let issueCount = 0;

            // Progress tracking
            const totalPhases = 3; // Heuristics, Symbolic, LLM
            const incrementPerPhase = 100 / totalPhases;
            let currentPhase = 0;

            // Use streaming for real-time feedback
            await client.analyzeFileStream(
                document.fileName,
                document.getText(),
                "default_project",
                async (event) => {
                    if (event.type === 'issue' && event.issue) {
                        issues.push(event.issue);
                        issueCount++;
                        // Add issue immediately for instant feedback
                        diagnostics.addDiagnostic(document, event.issue);
                        // Update progress message but don't increment yet
                        progress.report({
                            message: `Found ${issueCount} issue${issueCount !== 1 ? 's' : ''}...`
                        });
                    } else if (event.type === 'status' && event.message) {
                        currentPhase++;
                        // Update progress with status and increment
                        progress.report({
                            increment: incrementPerPhase,
                            message: `${event.message} (${Math.round((currentPhase / totalPhases) * 100)}%)`
                        });
                    } else if (event.type === 'complete') {
                        // Final update to 100%
                        progress.report({ increment: 100 });

                        const totalIssues = event.total_issues || issues.length;
                        if (totalIssues === 0) {
                            vscode.window.setStatusBarMessage('Autonoma: No issues found.', 3000);
                        } else {
                            vscode.window.setStatusBarMessage(
                                `Autonoma: Analysis complete. Found ${totalIssues} issue${totalIssues !== 1 ? 's' : ''}.`,
                                3000
                            );
                        }
                    } else if (event.type === 'error') {
                        const message = event.message || 'Unknown error';

                        if (message.includes('Connection refused') || message.includes('fetch failed')) {
                            const confirm = await vscode.window.showWarningMessage(
                                "Activating L5 Autonomy will automatically modify files. Autonoma will fix bugs without asking for permission. Are you sure?",
                                { modal: true },
                                "Yes, Deploy Autonoma"
                            );

                            if (confirm === "Yes, Deploy Autonoma") {
                                vscode.window.showErrorMessage(
                                    'Cannot connect to Autonoma daemon. Is it running?',
                                    'Open Troubleshooting'
                                ).then(selection => {
                                    if (selection === 'Open Troubleshooting') {
                                        vscode.env.openExternal(vscode.Uri.parse('https://github.com/hybrid-ai-team/hybrid-reviewer#troubleshooting'));
                                    }
                                });
                            }
                        } else if (message.includes('File too large')) {
                            vscode.window.showWarningMessage('File is too large for analysis (max 10MB).');
                        } else {
                            vscode.window.showErrorMessage(`Autonoma Error: ${message}`);
                        }
                    }
                }
            );
        });
    });

    // 2. Set API Key Command
    let setApiKeyCommand = vscode.commands.registerCommand('hybrid-reviewer.setApiKey', async () => {
        const provider = await vscode.window.showQuickPick(['autonoma', 'openai', 'anthropic'], {
            placeHolder: 'Select AI Provider',
            title: 'Set API Key'
        });

        if (provider) {
            const secretKey = await vscode.window.showInputBox({
                prompt: `Enter ${provider === 'autonoma' ? 'Autonoma License Key (Team Token)' : provider + ' API key'}`,
                password: true,
                placeHolder: provider === 'autonoma' ? 'sk_live_...' : 'sk-...'
            });

            if (secretKey) {
                try {
                    // Import dynamically to avoid circular dependencies if any
                    const { setApiKey } = require('./config');
                    await setApiKey(provider, secretKey);

                    if (provider === 'autonoma') {
                        // Validate format loosely
                        if (!secretKey.startsWith('sk_')) {
                            vscode.window.showWarningMessage('Warning: Autonoma keys usually start with sk_ ...');
                        }
                    }
                    vscode.window.showInformationMessage(`${provider === 'autonoma' ? 'Autonoma License Key' : provider + ' API key'} saved securely.`);
                } catch (error) {
                    vscode.window.showErrorMessage(`Failed to save key: ${error}`);
                }
            }
        }
    });

    context.subscriptions.push(analyzeCommand);
    context.subscriptions.push(setApiKeyCommand);

    context.subscriptions.push(
        vscode.commands.registerCommand('hybrid-reviewer.analyzeProject', () => {
            SummaryPanel.createOrShow(context.extensionUri);
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('hybrid-reviewer.runProjectAnalysis', async () => {
            vscode.window.withProgress({
                location: vscode.ProgressLocation.Notification,
                title: "Analyzing Project...",
                cancellable: true
            }, async (progress, token) => {
                try {
                    const issues = await client.analyzeProject(vscode.workspace.rootPath || "");
                    SummaryPanel.createOrShow(context.extensionUri, issues);
                } catch (e) {
                    vscode.window.showErrorMessage("Project analysis failed: " + e);
                }
            });
        })
    );
}
