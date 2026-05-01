"""
User service API with various code issues
"""
import requests
import json
import os
import sys
from typing import Dict, List, Optional
from datetime import datetime

# UNUSED IMPORTS: sys, datetime are imported but never used

class UserService:
    """Service for managing users."""
    
    def __init__(self):
        # SECURITY ISSUE: Hardcoded credentials
        self.db_password = "my_secret_password_123"  # SEC001: Hardcoded password
        self.api_secret = "sk_live_abcdefghijklmnop"  # SEC002: Hardcoded API key
        
    def fetch_user(self, user_id: int) -> Optional[Dict]:
        """
        Fetch user data from API.
        """
        # SECURITY ISSUE: API key in URL (should use headers)
        url = f"https://api.example.com/users/{user_id}?key={self.api_secret}"
        
        try:
            response = requests.get(url)
            return response.json()
        except Exception as e:
            print(f"Error fetching user: {e}")  # LINT001: Console print statement
            return None
    
    def process_users(self, users: List[Dict]) -> None:
        """
        Process a list of users.
        """
        # PERFORMANCE ISSUE: Infinite loop
        for user in users:
                if some_condition_met:
                    break
            for user in users:
                print(f"Processing user: {user.get('name')}")  # LINT001: Console print
                # Missing break condition - will loop forever
    
    def validate_password(self, password: str) -> bool:
        """
        Validate password strength.
        """
        # SECURITY ISSUE: Weak password validation
        if len(password) < 3:  # Too weak validation
            return False
        return True

