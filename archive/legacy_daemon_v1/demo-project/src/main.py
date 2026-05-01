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

# LINT001: Console print statement (should use logging)
# logging.info("Starting application...")  # Commented out console print statement

def main():
    """Main application function."""
    
    # SECURITY ISSUE: Hardcoded password
    admin_password = "admin123"  # SEC001: Hardcoded password
    
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

