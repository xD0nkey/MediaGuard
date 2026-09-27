from collections import deque
from datetime import datetime, timezone
from threading import Lock


class Activity:
    CATEGORIES = {"System", "Discord", "Error"}

    def __init__(self, capacity: int = 200):
        self._items = deque(maxlen=capacity)
        self._lock = Lock()

    def record(self, category: str, code: str):
        if category not in self.CATEGORIES or not code.replace("_", "").isalnum():
            raise ValueError("Activity accepts only known categories and codes")
        item = {"at": datetime.now(timezone.utc).isoformat(), "category": category, "code": code}
        with self._lock:
            self._items.appendleft(item)

    def recent(self, limit: int = 50):
        with self._lock:
            return list(self._items)[: max(0, min(limit, 200))]
