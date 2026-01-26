"""
Authentication module with security issues for demo
"""
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
    """
    Authenticate a user with username and password.
    """
    # SECURITY ISSUE: Using hardcoded credentials
    if username == "admin" and user_password == password:
        return True
    return False

# PERFORMANCE ISSUE: Infinite loop
def process_data():
    """Process data in an infinite loop."""
    while False: # Fixed infinite loop  # PERF001: Infinite loop
        # Missing break condition
        pass
