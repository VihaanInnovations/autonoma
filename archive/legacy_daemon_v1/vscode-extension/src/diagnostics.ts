import * as vscode from 'vscode';
import { AnalysisIssue } from './client';

export class DiagnosticsManager {
    private collection: vscode.DiagnosticCollection;

    constructor() {
        this.collection = vscode.languages.createDiagnosticCollection('autonoma');
    }

    updateDiagnostics(document: vscode.TextDocument, issues: AnalysisIssue[]) {
        const diagnostics: vscode.Diagnostic[] = [];

        for (const issue of issues) {
            // Line numbers in VS Code are 0-indexed, but our daemon returns 1-indexed
            const lineIndex = Math.max(0, issue.line - 1);

            // Create a range for the diagnostic. 
            // Ideally we'd have start/end column, but for now we'll mark the whole line range
            // or just the first character if column unknown.
            // Getting the line content to find range would be better.
            const line = document.lineAt(lineIndex);
            const range = line.range; // Mark entire line

            const severity = this.mapSeverity(issue.severity);

            const diagnostic = new vscode.Diagnostic(range, issue.message, severity);
            diagnostic.source = `Autonoma (${issue.source})`;
            diagnostic.code = issue.id;

            diagnostics.push(diagnostic);
        }

        this.collection.set(document.uri, diagnostics);
    }

    /**
     * Add a single issue to diagnostics (for streaming)
     */
    addDiagnostic(document: vscode.TextDocument, issue: AnalysisIssue) {
        const lineIndex = Math.max(0, issue.line - 1);

        try {
            const line = document.lineAt(lineIndex);
            const range = line.range;
            const severity = this.mapSeverity(issue.severity);

            const diagnostic = new vscode.Diagnostic(range, issue.message, severity);
            diagnostic.source = `Autonoma (${issue.source})`;
            diagnostic.code = issue.id;

            // Get existing diagnostics and add new one
            const existing = this.collection.get(document.uri) || [];

            // Check if this issue already exists (avoid duplicates)
            const exists = existing.some(d =>
                d.code === issue.id &&
                d.range.start.line === lineIndex
            );

            if (!exists) {
                this.collection.set(document.uri, [...existing, diagnostic]);
            }
        } catch (error) {
            // Line might be out of bounds, skip
            console.warn(`Could not add diagnostic for line ${issue.line}:`, error);
        }
    }

    clearDiagnostics(document: vscode.TextDocument) {
        this.collection.delete(document.uri);
    }

    private mapSeverity(severity: string): vscode.DiagnosticSeverity {
        switch (severity) {
            case 'high': return vscode.DiagnosticSeverity.Error;
            case 'medium': return vscode.DiagnosticSeverity.Warning;
            case 'low': return vscode.DiagnosticSeverity.Information;
            default: return vscode.DiagnosticSeverity.Hint;
        }
    }
}
