"""
Main application entry point with code issues
"""
import os
import sys
import json
import logging
from typing import Optional

# UNUSED IMPORTS: json is imported but never used

from auth.credentials import authenticate_user, get_api_key
from api.user_service import UserService

# Testing class attribute remediation
class Settings:
    API_KEY = os.environ["API_KEY"]  # SEC002: Fixable (class attribute)

# Real-world messy config with nested secrets
DEV_CONFIG = {
    "database": {
        "host": "localhost",
        "creds": {
            "user": "admin",
            "password": "nested_secret_value"  # SEC001: Refused (nested dict)
        }
    },
    "retry_policy": {"max_attempts": 3}
}

# Testing keyword argument remediation in function calls
def connect(db, password):
    logging.info(f"Connecting to {db}...")

connect(
    db="prod", 
    password=os.environ["PASSWORD"]
)  # SEC001: Fixable (keyword arg)

def main():
    """Main application function."""
    
    # Proving runtime awareness:
    # 1. This is a dynamic lookup (SHOULD BE IGNORED)
    dynamic_pass = get_api_key()
    
    # 2. This is a hardcoded secret in a call (SHOULD BE DETECTED BUT REFUSED)
    def authorize(token, context):
        logging.info(f"Authorizing {context}...")
    
    authorize("hardcoded_secret_token", context="demo")
    
    # SECURITY ISSUE: Hardcoded password
    admin_password = os.environ["ADMIN_PASSWORD"]  # SEC001: Hardcoded password
    
    # Initialize service
    service = UserService()
    
    # Authenticate
    username = input("Enter username: ")
    password = input("Enter password: ")
    
    if authenticate_user(username, password):
        logging.info("Authentication successful!")
    else:
        logging.info("Authentication failed!")
    
    # Process users
    users = [{"name": "Alice"}, {"name": "Bob"}]
    
    # PERFORMANCE ISSUE: Infinite loop
    while users:
        logging.info("Processing users...")
        service.process_users(users)
        # Missing break condition

if __name__ == "__main__":
    main()