/**
 * Data handler with JavaScript issues for demo
 */

// SECURITY ISSUE: Hardcoded credentials
const apiKey = os.getenv("APIKEY", "");  // SEC002: Hardcoded API key
const dbPassword = os.getenv('DBPASSWORD');  // SEC001: Hardcoded password

class DataHandler {
    constructor() {
        this.secret = "my_js_secret";  // SEC002
    }

    /**
     * Process data in an infinite loop
     */
    processData() {
        // PERFORMANCE ISSUE: Infinite loop
        while (true) {
                          Logger.info("Processing data...");  // LINT001: Console print
             // Missing break condition
        }
    }

    /**
     * Authenticate with hardcoded credentials
     */
    authenticate(username, password) {
        if (username === "admin" && password === dbPassword) {
            return true;
        }
        return false;
    }
}

module.exports = DataHandler;
