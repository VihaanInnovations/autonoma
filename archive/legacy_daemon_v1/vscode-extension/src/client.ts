import axios from 'axios';
import { ExtensionConfig, getApiKey } from './config';

export interface AnalysisIssue {
    id: string;
    line: number;
    message: string;
    type: 'lint' | 'security' | 'performance' | 'refactor';
    severity: 'low' | 'medium' | 'high';
    source: string;
}

export interface StreamEvent {
    type: 'issue' | 'status' | 'complete' | 'error';
    issue?: AnalysisIssue;
    message?: string;
    total_issues?: number;
}

export type StreamCallback = (event: StreamEvent) => void;

export class ReviewerClient {
    private config: ExtensionConfig;

    constructor(config: ExtensionConfig) {
        this.config = config;
    }

    async checkDaemonHealth(): Promise<boolean> {
        try {
            // Short timeout for health check
            const timeoutSignal = AbortSignal.timeout(2000);
            const response = await fetch(`${this.config.daemonUrl}/health`, {
                method: 'GET',
                signal: timeoutSignal
            });
            return response.ok;
        } catch (error) {
            console.error('Daemon health check failed:', error);
            return false;
        }
    }

    /**
     * Traditional analysis - returns all issues at once (backward compatible)
     */
    async analyzeFile(filePath: string, content: string, projectId: string): Promise<AnalysisIssue[]> {
        try {
            const response = await axios.post(`${this.config.daemonUrl}/analyze`, {
                file_path: filePath,
                content: content,
                project_id: projectId,
                user_config: {
                    enable_local_llm: this.config.enableLocalLLM,
                    enable_cloud_llm: this.config.enableCloudLLM,
                    cloud_provider: this.config.cloudProvider,
                    cloud_model: this.config.cloudModel,
                    local_model: this.config.localModel,
                    disabled_rules: this.config.disabledRules
                }
            });

            if (response.data && response.data.issues) {
                return response.data.issues;
            }
            return [];
        } catch (error) {
            console.error('Error communicating with analysis daemon:', error);
            // In a real app we might want to show an error message or retry
            return [];
        }
    }

    /**
     * Streaming analysis - calls callback for each event (issue, status, complete, error)
     * Returns a promise that resolves when streaming is complete
     */
    async analyzeFileStream(
        filePath: string,
        content: string,
        projectId: string,
        onEvent: StreamCallback
    ): Promise<void> {
        try {
            // Fetch API keys securely
            const openaiKey = await getApiKey('openai');
            const anthropicKey = await getApiKey('anthropic');
            // Prioritize config teamToken, but allow getting from secrets if we migrate
            const teamToken = this.config.teamToken || await getApiKey('autonoma');

            const headers: Record<string, string> = {
                'Content-Type': 'application/json'
            };

            if (teamToken) {
                headers['Authorization'] = `Bearer ${teamToken}`;
            }

            const response = await fetch(`${this.config.daemonUrl}/analyze/stream`, {
                method: 'POST',
                headers: headers,
                body: JSON.stringify({
                    file_path: filePath,
                    content: content,
                    project_id: projectId,
                    user_config: {
                        enable_local_llm: this.config.enableLocalLLM,
                        enable_cloud_llm: this.config.enableCloudLLM,
                        cloud_provider: this.config.cloudProvider,
                        cloud_model: this.config.cloudModel,
                        local_model: this.config.localModel,
                        disabled_rules: this.config.disabledRules,
                        api_keys: {
                            openai: openaiKey,
                            anthropic: anthropicKey
                        }
                    }
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            if (!response.body) {
                throw new Error('Response body is null');
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();

                if (done) {
                    break;
                }

                // Decode chunk and add to buffer
                buffer += decoder.decode(value, { stream: true });

                // Process complete SSE messages (lines ending with \n\n)
                const lines = buffer.split('\n');
                buffer = lines.pop() || ''; // Keep incomplete line in buffer

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        try {
                            const data = JSON.parse(line.slice(6)); // Remove 'data: ' prefix
                            onEvent(data as StreamEvent);
                        } catch (e) {
                            console.error('Error parsing SSE data:', e, line);
                        }
                    }
                }
            }

            // Process any remaining data in buffer
            if (buffer.trim()) {
                const lines = buffer.split('\n');
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        try {
                            const data = JSON.parse(line.slice(6));
                            onEvent(data as StreamEvent);
                        } catch (e) {
                            console.error('Error parsing SSE data:', e, line);
                        }
                    }
                }
            }

        } catch (error) {
            console.error('Error streaming from analysis daemon:', error);
            onEvent({
                type: 'error',
                message: error instanceof Error ? error.message : 'Unknown error'
            });
        }
    }

    async analyzeProject(projectPath: string): Promise<AnalysisIssue[]> {
        try {
            const response = await axios.post(`${this.config.daemonUrl}/analyze/project`, {
                project_path: projectPath,
                user_config: {
                    enable_local_llm: this.config.enableLocalLLM,
                    enable_cloud_llm: this.config.enableCloudLLM,
                    cloud_provider: this.config.cloudProvider,
                    cloud_model: this.config.cloudModel,
                    local_model: this.config.localModel,
                    disabled_rules: this.config.disabledRules
                }
            });

            if (response.data && response.data.issues) {
                return response.data.issues;
            }
            return [];
        } catch (error) {
            console.error('Error analyzing project:', error);
            throw error;
        }
    }
}
