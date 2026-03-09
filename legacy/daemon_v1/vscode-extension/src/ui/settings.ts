import * as vscode from 'vscode';

export class Settings {
    private static getConfiguration() {
        return vscode.workspace.getConfiguration('autonoma');
    }

    static get isLocalLLMEnabled(): boolean {
        return this.getConfiguration().get<boolean>('enableLocalLLM', false);
    }

    static async setLocalLLMEnabled(value: boolean): Promise<void> {
        await this.getConfiguration().update('enableLocalLLM', value, vscode.ConfigurationTarget.Global);
    }

    static get isCloudLLMEnabled(): boolean {
        return this.getConfiguration().get<boolean>('enableCloudLLM', true);
    }

    static async setCloudLLMEnabled(value: boolean): Promise<void> {
        await this.getConfiguration().update('enableCloudLLM', value, vscode.ConfigurationTarget.Global);
    }

    static get modelPreference(): string {
        return this.getConfiguration().get<string>('modelPreference', 'auto');
    }

    static async setModelPreference(value: string): Promise<void> {
        await this.getConfiguration().update('modelPreference', value, vscode.ConfigurationTarget.Global);
    }

    static get ruleOverrides(): Record<string, boolean> {
        return this.getConfiguration().get<Record<string, boolean>>('ruleOverrides', {});
    }

    static async setRuleOverride(ruleId: string, enabled: boolean): Promise<void> {
        const overrides = this.ruleOverrides;
        overrides[ruleId] = enabled;
        await this.getConfiguration().update('ruleOverrides', overrides, vscode.ConfigurationTarget.Workspace);
    }
}
