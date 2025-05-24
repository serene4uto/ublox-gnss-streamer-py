import threading
from collections import deque

class ThreadSafeDeque:
    def __init__(self, maxlen=None):
        self.deque = deque(maxlen=maxlen)
        self.lock = threading.Lock()

    def append(self, item):
        with self.lock:
            self.deque.append(item)

    def popleft(self):
        with self.lock:
            if self.deque:
                return self.deque.popleft()
            else:
                return None

    def __len__(self):
        with self.lock:
            return len(self.deque)

    def is_empty(self):
        with self.lock:
            return len(self.deque) == 0
