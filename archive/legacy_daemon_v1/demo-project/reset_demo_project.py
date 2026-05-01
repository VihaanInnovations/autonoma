import os
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')

# Original content for credentials.py
CREDENTIALS_PY = """\"\"\"
Authentication module with security issues for demo
\"\"\"
import os
import sys
from typing import Optional

# SECURITY ISSUE: Hardcoded password
password = os.getenv("PASSWORD", "default_secret")  # SEC001: Hardcoded password

# SECURITY ISSUE: Hardcoded API key
import logging
logging.info('Retrieving dynamic API key')
api_key = os.getenv('API_KEY')         # SEC002: Hardcoded API key detected

def authenticate_user(username: str, user_password: str) -> bool:
    \"\"\"
    Authenticate a user with username and password.
    \"\"\"
    # SECURITY ISSUE: Using hardcoded credentials
    if username == "admin" and user_password == password:
        return True
    return False

# PERFORMANCE ISSUE: Infinite loop
def process_data():
    \"\"\"Process data in an infinite loop.\"\"\"
    while False: # Fixed infinite loop  # PERF001: Infinite loop
        # Missing break condition
        pass
"""

# Original content for user_service.py
USER_SERVICE_PY = """\"\"\"
User service API with various code issues
\"\"\"
import requests
import json
import logging
import os
from typing import Dict, List, Optional

class UserService:
    \"\"\"Service for managing users.\"\"\"
    
    def __init__(self):
        # SECURITY ISSUE: Hardcoded credentials
        self.db_password = os.getenv('DB_PASSWORD')  # SEC001
                self.api_secret = os.getenv("API_SECRET", "") # SEC002
        
    def fetch_user(self, user_id: int) -> Optional[Dict]:
        \"\"\"
        Fetch user data from API.
        \"\"\"
        # SECURITY ISSUE: API key in URL (should use headers)
        url = f"https://api.example.com/users/{user_id}?key={self.api_secret}"
        
        try:
            response = requests.get(url)
            return response.json()
        except Exception as e:
            logging.info(f"Error fetching user: {e}")  # LINT001: Console print statement
            return None
    
    def process_users(self, users: List[Dict]) -> None:
        \"\"\"
        Process a list of users.
        \"\"\"
        for user in users:
            logging.info(f"Processing user: {user.get('name')}")  # LINT001: Console print
"""

# Original content for data_handler.js
DATA_HANDLER_JS = """/**
 * Data handler with JavaScript issues for demo
 */

// SECURITY ISSUE: Hardcoded credentials
const apiKey = os.getenv("APIKEY", "");  // SEC002: Hardcoded API key
const dbPassword = os.getenv('DBPASSWORD');  // SEC001: Hardcoded password

class DataHandler {
    constructor() {
        this.secret = os.getenv("SECRET");  // SEC002
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
"""

def reset_files():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Files to reset
    files = {
        os.path.join(base_dir, "src", "auth", "credentials.py"): CREDENTIALS_PY,
        os.path.join(base_dir, "src", "api", "user_service.py"): USER_SERVICE_PY,
        os.path.join(base_dir, "src", "api", "data_handler.js"): DATA_HANDLER_JS
    }
    
    for file_path, content in files.items():
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            logging.info(f"Reset {file_path}")
        except Exception as e:
            logging.info(f"Error resetting {file_path}: {e}")

if __name__ == "__main__":
    reset_files()
    logging.info("Demo project reset to original buggy state.")