import * as vscode from 'vscode';

export interface ExtensionConfig {
    enableLocalLLM: boolean;
    enableCloudLLM: boolean;
    cloudProvider: string;
    cloudModel: string;
    localModel: string;
    disabledRules: string[];
    apiKeys: Record<string, string>;
    daemonUrl: string;
    teamUrl: string;
    teamToken: string;
}

export function getConfig(): ExtensionConfig {
    const config = vscode.workspace.getConfiguration('autonoma');
    return {
        enableLocalLLM: config.get<boolean>('enableLocalLLM', false),
        enableCloudLLM: config.get<boolean>('enableCloudLLM', false),
        cloudProvider: config.get<string>('cloudProvider', 'openai'),
        cloudModel: config.get<string>('cloudModel', 'gpt-4-turbo-preview'),
        localModel: config.get<string>('localModel', 'llama3'),
        disabledRules: config.get<string[]>('disabledRules', []),
        apiKeys: config.get<Record<string, string>>('apiKeys', {}),
        daemonUrl: config.get<string>('daemonUrl', 'http://127.0.0.1:8000'),
        teamUrl: config.get<string>('teamUrl', ''),
        teamToken: config.get<string>('teamToken', '')
    };
}

const SECRET_KEY_PREFIX = 'autonoma.apiKey.';
let secretStorage: vscode.SecretStorage | undefined;

export function initSecrets(context: vscode.ExtensionContext) {
    secretStorage = context.secrets;
}

export async function getApiKey(provider: string): Promise<string | undefined> {
    if (!secretStorage) {
        console.error('Secret storage not initialized');
        return undefined;
    }
    try {
        const key = `${SECRET_KEY_PREFIX}${provider}`;
        return await secretStorage.get(key);
    } catch (error) {
        console.error(`Failed to get API key for ${provider}:`, error);
        return undefined;
    }
}

export async function setApiKey(provider: string, value: string): Promise<void> {
    if (!secretStorage) {
        throw new Error('Secret storage not initialized');
    }
    try {
        const key = `${SECRET_KEY_PREFIX}${provider}`;
        return await secretStorage.store(key, value);
    } catch (error) {
        console.error(`Failed to set API key for ${provider}:`, error);
        throw error;
    }
}

export async function deleteApiKey(provider: string): Promise<void> {
    if (!secretStorage) {
        return;
    }
    const key = `${SECRET_KEY_PREFIX}${provider}`;
    await secretStorage.delete(key);
}
