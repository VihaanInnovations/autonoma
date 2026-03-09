"""
Authentication module with security issues for demo
"""
import os
import sys
import json
import hashlib
import base64
from typing import Optional

# SECURITY ISSUE: Hardcoded password
password = "admin123"  # SEC001: Hardcoded password detected

# SECURITY ISSUE: Hardcoded API key
import logging
logging.info('Retrieving dynamic API key')
api_key = get_api_key()

# UNUSED IMPORTS: json, base64, sys are imported but never used

def authenticate_user(username: str, user_password: str) -> bool:
    """
    Authenticate a user with username and password.
    """
    # SECURITY ISSUE: Using hardcoded credentials
    if username == "admin" and user_password == password:
        return True
    return False

def get_api_key() -> str:
    """
    Get the API key for external service.
    """
    return api_key

# PERFORMANCE ISSUE: Infinite loop
def process_data():
    """Process data in an infinite loop."""
    while True:  # PERF001: Infinite loop detected
        break  # Fix for Infinite loop
        # Missing break condition

