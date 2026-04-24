import * as vscode from 'vscode';
import axios from 'axios';
import { ExtensionConfig } from './config';

export class LocalAIFixProvider implements vscode.CodeActionProvider {
    constructor(private config: ExtensionConfig) { }

    provideCodeActions(document: vscode.TextDocument, range: vscode.Range | vscode.Selection, context: vscode.CodeActionContext, token: vscode.CancellationToken): vscode.ProviderResult<(vscode.Command | vscode.CodeAction)[]> {

        // Only provide if we have diagnostics
        if (context.diagnostics.length === 0) {
            return [];
        }

        const actions: vscode.CodeAction[] = [];

        for (const diagnostic of context.diagnostics) {
            // Check if it's our diagnostic (source starts with "Autonoma")
            // Or just allow generic? For now, let's allow any.

            const action = new vscode.CodeAction(`Fix with Local AI: ${diagnostic.message}`, vscode.CodeActionKind.QuickFix);
            action.diagnostics = [diagnostic];
            action.isPreferred = true;

            // Define the command that will run when selected
            action.command = {
                command: 'autonoma.applyFix',
                title: 'Apply Fix',
                arguments: [document, diagnostic.range, diagnostic.message]
            };

            actions.push(action);
        }

        return actions;
    }
}

export async function registerFixCommand(context: vscode.ExtensionContext, config: ExtensionConfig) {
    // Register the command handler
    context.subscriptions.push(vscode.commands.registerCommand('autonoma.applyFix', async (document: vscode.TextDocument, range: vscode.Range, message: string) => {

        const code = document.getText(range);
        if (!code.trim()) return;

        try {
            vscode.window.showInformationMessage("Asking Local AI to fix...");

            const response = await axios.post(`${config.daemonUrl}/analyze/fix`, {
                code: code,
                issue: message,
                model: config.localModel
            });

            const fixedCode = response.data.fixed_code;

            if (fixedCode && fixedCode !== code) {
                const edit = new vscode.WorkspaceEdit();
                edit.replace(document.uri, range, fixedCode);
                await vscode.workspace.applyEdit(edit);
                vscode.window.showInformationMessage("Fix applied by Local AI!");
            } else {
                vscode.window.showWarningMessage("Local AI could not generate a better fix.");
            }

        } catch (error) {
            vscode.window.showErrorMessage(`Fix failed: ${error}`);
        }
    }));
}
