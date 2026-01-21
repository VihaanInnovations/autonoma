import asyncio
import json
from typing import Dict, Any
from ..db.db import get_db_connection

class TelemetryQueue:
    def __init__(self):
        self.queue = asyncio.Queue()

    async def add_event(self, event: Dict[str, Any]):
        await self.queue.put(event)

    async def process_queue(self):
        batch = []
        while True:
            try:
                # Wait for an item
                event = await self.queue.get()
                batch.append(event)
                
                # Try to get more items to batch write (up to 10 or until empty)
                for _ in range(10):
                    try:
                        event = self.queue.get_nowait()
                        batch.append(event)
                    except asyncio.QueueEmpty:
                        break
                
                await self.write_batch(batch)
                batch = []
                
            except Exception as e:
                print(f"Error processing telemetry: {e}")
            finally:
                # Mark tasks as done
                for _ in range(len(batch) + 1): # +1 for the first get()
                    try:
                        self.queue.task_done()
                    except ValueError:
                        pass

    async def write_batch(self, events: list):
        if not events:
            return
            
        conn = get_db_connection()
        cursor = conn.cursor()
        
        for event in events:
            cursor.execute("""
                INSERT INTO TelemetryEvent (event_id, user_id, event_type, metadata)
                VALUES (?, ?, ?, ?)
            """, (event.get("event_id"), event.get("user_id"), event.get("event_type"), json.dumps(event.get("metadata", {}))))
            
        conn.commit()
        conn.close()
