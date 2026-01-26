"""
User service API with various code issues
"""
import requests
import json
import logging
import os
from typing import Dict, List, Optional

class UserService:
    """Service for managing users."""
    
    def __init__(self):
        # SECURITY ISSUE: Hardcoded credentials
        self.db_password = os.getenv('DB_PASSWORD')  # SEC001
                self.api_secret = os.getenv("API_SECRET", "") # SEC002
        
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
            logging.info(f"Error fetching user: {e}")  # LINT001: Console print statement
            return None
    
    def process_users(self, users: List[Dict]) -> None:
        """
        Process a list of users.
        """
        for user in users:
            logging.info(f"Processing user: {user.get('name')}")  # LINT001: Console print
