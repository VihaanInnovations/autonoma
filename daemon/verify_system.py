import asyncio
import os
import sys
import json
from pathlib import Path

# Add current dir to sys.path so we can import modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from db.db import init_db, get_db_connection
from queues.analysis_queue import AnalysisQueue

async def main():
    print("Initializing DB...")
    init_db()
    
    queue = AnalysisQueue()
    
    # Test Content with Heuristic Issues
    content = """
    def login():
        password = "secret_password" 
        print("Logging in")
        while True:
            pass
    """
    
    task = {
        "file_path": "/test/login.py",
        "content": content,
        "project_id": "test_project",
        "user_config": {
            "enable_local_llm": False,
            "enable_cloud_llm": False
        }
    }
    
    print("Running Analysis 1 (Fresh)...")
    issues = await queue.run_analysis(task)
    print(f"Issues found: {len(issues)}")
    
    for issue in issues:
        print(f" - [{issue['type']}] {issue['message']}")
        
    # Verify Heuristics
    ids = [i['id'] for i in issues]
    assert "SEC001" in ids, "Failed to detect hardcoded password"
    assert "PERF001" in ids, "Failed to detect infinite loop"
    assert "LINT001" in ids, "Failed to detect print statement"
    
    print("\nRunning Analysis 2 (Cached)...")
    # Should hit cache
    issues_cached = await queue.run_analysis(task)
    # In the real implementation, run_analysis prints "Cache hit" to stdout, 
    # but programmatically we can check if it returns the same result.
    assert len(issues_cached) == len(issues)
    print("Cached analysis match.")
    
    # Verify DB
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) as count FROM FileAnalysisCache")
    row = cursor.fetchone()
    print(f"\nDB Cache Entries: {row['count']}")
    conn.close()
    
    print("\nVerification Successful!")

if __name__ == "__main__":
    asyncio.run(main())
