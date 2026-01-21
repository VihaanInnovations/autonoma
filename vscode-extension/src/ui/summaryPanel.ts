import * as vscode from 'vscode';
import { Settings } from './settings';

export class SummaryPanel {
    public static currentPanel: SummaryPanel | undefined;
    private readonly _panel: vscode.WebviewPanel;
    private _disposables: vscode.Disposable[] = [];

    private constructor(panel: vscode.WebviewPanel, extensionUri: vscode.Uri) {
        this._panel = panel;
        this._panel.onDidDispose(() => this.dispose(), null, this._disposables);

        // Handle messages from the webview
        this._panel.webview.onDidReceiveMessage(
            message => {
                switch (message.command) {
                    case 'analyzeProject':
                        vscode.commands.executeCommand('hybrid-reviewer.runProjectAnalysis');
                        break;
                    case 'toggleRule':
                        Settings.setRuleOverride(message.ruleId, message.enabled);
                        break;
                    case 'openFile':
                        vscode.workspace.openTextDocument(message.filePath).then(doc => {
                            vscode.window.showTextDocument(doc, { selection: new vscode.Range(message.line - 1, 0, message.line - 1, 0) });
                        });
                        break;
                }
            },
            null,
            this._disposables
        );

        this._panel.webview.html = this._getHtmlForWebview(this._panel.webview);
    }

    public static createOrShow(extensionUri: vscode.Uri, issues: any[] = []) {
        const column = vscode.window.activeTextEditor
            ? vscode.window.activeTextEditor.viewColumn
            : undefined;

        if (SummaryPanel.currentPanel) {
            SummaryPanel.currentPanel._panel.reveal(column);
            SummaryPanel.currentPanel.update(issues);
            return;
        }

        const panel = vscode.window.createWebviewPanel(
            'hybridReviewerSummary',
            'Hybrid Reviewer Summary',
            column || vscode.ViewColumn.One,
            {
                enableScripts: true,
                localResourceRoots: [vscode.Uri.joinPath(extensionUri, 'media')]
            }
        );

        SummaryPanel.currentPanel = new SummaryPanel(panel, extensionUri);
        SummaryPanel.currentPanel.update(issues);
    }

    public update(issues: any[]) {
        this._panel.webview.postMessage({ command: 'updateIssues', issues: issues });
    }

    public dispose() {
        SummaryPanel.currentPanel = undefined;
        this._panel.dispose();
        while (this._disposables.length) {
            const x = this._disposables.pop();
            if (x) {
                x.dispose();
            }
        }
    }

    private _getHtmlForWebview(webview: vscode.Webview) {
        return `<!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Hybrid Reviewer Summary</title>
            <style>
                body { font-family: sans-serif; padding: 20px; }
                .issue-group { margin-bottom: 20px; border: 1px solid #ccc; padding: 10px; border-radius: 5px; }
                .issue-group h3 { margin-top: 0; }
                .issue { display: flex; align-items: center; justify-content: space-between; padding: 5px 0; border-bottom: 1px solid #eee; }
                .issue:last-child { border-bottom: none; }
                .severity { font-weight: bold; margin-right: 10px; }
                .severity.error { color: #d32f2f; }
                .severity.warning { color: #f57c00; }
                .location { color: #666; font-size: 0.9em; cursor: pointer; text-decoration: underline;}
                .actions { display: flex; gap: 10px; }
                button { cursor: pointer; padding: 5px 10px; background: #007acc; color: white; border: none; border-radius: 3px; }
                button:hover { background: #005f9e; }
            </style>
        </head>
        <body>
            <h1>Project Analysis Summary</h1>
            <div style="margin-bottom: 20px;">
                <button onclick="analyzeProject()">Analyze Project</button>
            </div>
            <div id="issues-container">Waiting for analysis...</div>

            <script>
                const vscode = acquireVsCodeApi();

                function analyzeProject() {
                    vscode.postMessage({ command: 'analyzeProject' });
                    document.getElementById('issues-container').innerText = 'Analyzing...';
                }

                function openFile(filePath, line) {
                    vscode.postMessage({ command: 'openFile', filePath: filePath, line: line });
                }

                window.addEventListener('message', event => {
                    const message = event.data;
                    switch (message.command) {
                        case 'updateIssues':
                            renderIssues(message.issues);
                            break;
                    }
                });

                function renderIssues(issues) {
                    const container = document.getElementById('issues-container');
                    container.innerHTML = '';

                    if (!issues || issues.length === 0) {
                        container.innerHTML = '<p>No issues found.</p>';
                        return;
                    }

                    // Group by file
                    const grouped = {};
                    issues.forEach(issue => {
                        const file = issue.file_path || 'unknown';
                        if (!grouped[file]) grouped[file] = [];
                        grouped[file].push(issue);
                    });

                    Object.keys(grouped).forEach(file => {
                        const groupDiv = document.createElement('div');
                        groupDiv.className = 'issue-group';
                        
                        const header = document.createElement('h3');
                        header.innerText = file;
                        groupDiv.appendChild(header);

                        grouped[file].forEach(issue => {
                            const issueDiv = document.createElement('div');
                            issueDiv.className = 'issue';
                            
                            const left = document.createElement('div');
                            left.innerHTML = \`
                                <span class="severity \${issue.severity}">\${issue.severity.toUpperCase()}</span>
                                <span class="message">\${issue.message}</span>
                                <span class="location" onclick="openFile('\${issue.original_path || issue.file_path}', \${issue.line})">line \${issue.line}</span>
                            \`;
                            
                            issueDiv.appendChild(left);
                            groupDiv.appendChild(issueDiv);
                        });

                        container.appendChild(groupDiv);
                    });
                }
            </script>
        </body>
        </html>`;
    }
}
