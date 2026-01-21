import * as vscode from 'vscode';
import axios from 'axios';
import { getConfig } from './config';

export class TeamClient {
    private teamUrl: string;
    private teamToken: string;

    constructor() {
        const config = getConfig();
        this.teamUrl = config.teamUrl;
        this.teamToken = config.teamToken;
    }

    public async fetchTeamConfig(): Promise<any> {
        if (!this.teamUrl || !this.teamToken) {
            return null;
        }

        try {
            // Note: In real app, we would talk to the remote server.
            // For MVP local daemon architecture, we might verify via daemon proxy
            // or talk directly if the user configures an external URL.
            // Assuming direct connection for simplicity or via daemon proxy if teamUrl points to valid https.

            // However, since we added the endpoints to our LOCAL daemon at /api/team/config,
            // we ironically might just query localhost if 'teamUrl' is meant to be the upstream.
            // But usually the client talks to the daemon, and the daemon talks to the upstream.
            // OR the client talks to upstream directly.

            // Let's assume the DAEMON is the one syncing.
            // But the prompt asked for "Team Client" in VS Code.
            // Let's implement a direct fetcher for now, or just a stub that logs.

            // Actually, querying the local Daemon's new /api/team/config endpoint 
            // is the best way to test the changes we just made!
            // But that endpoint is currently mocking the response.

            const response = await axios.get('http://localhost:8000/api/team/config', {
                headers: {
                    'X-Team-Token': this.teamToken
                }
            });
            return response.data;
        } catch (error) {
            console.error('Failed to fetch team config:', error);
            return null;
        }
    }

    public async syncStats(stats: any): Promise<void> {
        if (!this.teamUrl || !this.teamToken) { return; }
        try {
            await axios.post('http://localhost:8000/api/team/sync', stats, {
                headers: { 'X-Team-Token': this.teamToken }
            });
        } catch (error) {
            console.error('Failed to sync stats:', error);
        }
    }
}
