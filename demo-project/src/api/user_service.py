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
        # We need these for the legacy auth system
        self.db_password = os.environ["DB_PASSWORD"]  # SEC001
        self.api_secret = os.environ["API_SECRET"]        # SEC002
        
        # TODO: Refactor this into a proper config loader
        # But for now, we keep it inline to 'get things done'
        self.internal_id = "SYS-12345" 
        self.session_timeout = 3600 # 1 hour

    def demo_refusal(self, user: str):
        """EDGE CASE: Complex expression (refused by design)"""
        password = f"{user}_secret_password"  # SEC001: Refused (f-string)
        return password
        
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
        for user in users:
            # PERFORMANCE ISSUE: Infinite loop
            if True: # Simulating some condition
                break
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
