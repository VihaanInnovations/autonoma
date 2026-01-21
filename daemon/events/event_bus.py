import asyncio
from typing import Dict, Any, List, Callable
import json
import logging

logger = logging.getLogger("hybrid-reviewer")

class EventBus:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(EventBus, cls).__new__(cls)
            cls._instance._subscribers = []
            logger.info("EventBus initialized")
        return cls._instance

    def __init__(self):
        # Already initialized in __new__
        pass

    async def publish(self, event_type: str, payload: Dict[str, Any]):
        """Publish an event to all subscribers"""
        event = {
            "type": event_type,
            "payload": payload,
            "timestamp": asyncio.get_event_loop().time()
        }
        
        # Notify all subscriber queues
        # Filter out closed queues
        active_subs = []
        for q in self._subscribers:
            try:
                q.put_nowait(event)
                active_subs.append(q)
            except asyncio.QueueFull:
                logger.warning("EventBus subscriber queue full, dropping event")
                active_subs.append(q) # Keep it, just dropped this one
            except Exception as e:
                logger.debug(f"Removing dead subscriber: {e}")
                
        self._subscribers = active_subs

    def subscribe(self) -> asyncio.Queue:
        """Subscribe to events. Returns an async Queue."""
        q = asyncio.Queue(maxsize=100)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        """Unsubscribe"""
        if q in self._subscribers:
            self._subscribers.remove(q)

# Global accessor
_event_bus = EventBus()

def get_event_bus():
    return _event_bus
