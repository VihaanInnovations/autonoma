/**
 * Data handler with JavaScript issues for demo
 */

// UNUSED IMPORTS: These are imported but never used
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

// SECURITY ISSUE: Hardcoded credentials
const apiKey = "sk-1234567890abcdef";  // SEC002: Hardcoded API key
const dbPassword = "admin123";  // SEC001: Hardcoded password

class DataHandler {
    constructor() {
        this.secret = "my_secret_key_12345";  // SEC002: Hardcoded secret
    }

    /**
     * Process data in an infinite loop
     */
    processData() {
        // PERFORMANCE ISSUE: Infinite loop
        while (true) {  // PERF001: Infinite loop detected
            console.log("Processing data...");  // LINT001: Console print
            // Missing break condition
        }
    }

    /**
     * Authenticate with hardcoded credentials
     */
    authenticate(username, password) {
        // SECURITY ISSUE: Hardcoded credentials
        if (username === "admin" && password === dbPassword) {
            return true;
        }
        return false;
    }

    /**
     * Make API call with exposed credentials
     */
    async fetchData() {
        // SECURITY ISSUE: API key in URL
        const url = `https://api.example.com/data?key=${apiKey}`;

        try {
            const response = await fetch(url);
            return await response.json();
        } catch (error) {
            console.log(`Error: ${error}`);  // LINT001: Console print
            return null;
        }
    }
}

module.exports = DataHandler;

