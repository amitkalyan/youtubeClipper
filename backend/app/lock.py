"""One lock for SQLite and the job queue.

The worker and the request thread share a single connection. The lock is an
RLock so queue code can update the database while it already holds the lock.
Condition.wait() only unlocks an RLock once, so the worker must not touch the
database inside the same block where it waits.
"""

import threading

lock = threading.RLock()
