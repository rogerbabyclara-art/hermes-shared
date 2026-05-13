---
name: sqlite-threading-deadlock
description: Diagnose and fix SQLite threading issues and deadlocks in Python applications
tags: [sqlite, threading, deadlock, python, concurrency]
---

# SQLite Threading and Deadlock Issues

## When to use this skill

- Tests hang or timeout when accessing SQLite database
- Application freezes during concurrent database operations
- "database is locked" errors in multi-threaded Python apps
- Reentrant lock acquisition (method with lock calls another method with same lock)

## Symptoms

1. **Tests timeout** - pytest hangs indefinitely on database operations
2. **Deadlock pattern** - method holding lock calls another method that tries to acquire same lock
3. **Thread safety errors** - "SQLite objects created in a thread can only be used in that same thread"

## Diagnosis steps

1. **Identify the deadlock pattern**:
   ```python
   # BAD: Deadlock pattern
   def method_a(self):
       with self._lock:
           result = self.method_b()  # method_b also tries to acquire self._lock
   
   def method_b(self):
       with self._lock:  # DEADLOCK: lock already held by method_a
           # ...
   ```

2. **Quick test for deadlock**:
   ```bash
   timeout 10 python -c "
   from your_module import YourClass
   obj = YourClass()
   obj.method_that_might_deadlock()
   "
   ```
   If it times out, you have a deadlock.

3. **Check for threading.RLock vs threading.Lock**:
   - `threading.Lock` - NOT reentrant, deadlocks if same thread acquires twice
   - `threading.RLock` - Reentrant, same thread can acquire multiple times
   - SQLite + threading usually needs `RLock` OR careful lock-free internal methods

## Solution patterns

### Pattern 1: Internal lock-free methods (Recommended)

Split methods into public (with lock) and internal (no lock):

```python
import threading
import sqlite3

class EventStore:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()  # Regular Lock is fine
    
    # Public method - acquires lock
    def get_by_fingerprint(self, fp):
        with self._lock:
            return self._get_by_fingerprint_unlocked(fp)
    
    # Internal method - NO LOCK, assumes caller holds lock
    def _get_by_fingerprint_unlocked(self, fp):
        row = self.conn.execute(
            "SELECT * FROM events WHERE fingerprint = ?", (fp,)
        ).fetchone()
        return row
    
    # Public method that needs to call another query
    def upsert(self, event):
        with self._lock:
            # Call internal unlocked version
            existing = self._get_by_fingerprint_unlocked(event.fingerprint)
            if existing:
                # update
                self.conn.execute("UPDATE ...", ...)
            else:
                # insert
                self.conn.execute("INSERT ...", ...)
            self.conn.commit()
```

### Pattern 2: Use RLock (Alternative)

If you can't refactor, use reentrant lock:

```python
import threading

class EventStore:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.RLock()  # Reentrant lock
    
    def get_by_fingerprint(self, fp):
        with self._lock:  # Can be acquired multiple times by same thread
            # ...
    
    def upsert(self, event):
        with self._lock:
            existing = self.get_by_fingerprint(event.fingerprint)  # OK with RLock
            # ...
```

**Trade-off**: RLock is slightly slower and can hide design issues.

## Common SQLite threading mistakes

1. **Missing `check_same_thread=False`**:
   ```python
   # BAD: Will fail in multi-threaded app
   conn = sqlite3.connect('db.sqlite')
   
   # GOOD: Allow connection sharing (with proper locking)
   conn = sqlite3.connect('db.sqlite', check_same_thread=False)
   ```

2. **No locking at all**:
   ```python
   # BAD: Race conditions
   class Store:
       def __init__(self):
           self.conn = sqlite3.connect('db.sqlite', check_same_thread=False)
       
       def insert(self, data):
           self.conn.execute("INSERT ...", data)  # NOT THREAD-SAFE
   ```

3. **Locking only writes, not reads**:
   ```python
   # BAD: Reads can see inconsistent state
   def get_stats(self):
       # No lock - might read while another thread is writing
       return self.conn.execute("SELECT COUNT(*) ...").fetchone()
   ```

## Testing for thread safety

Create a test that hammers the database from multiple threads:

```python
import threading
import tempfile
from your_module import EventStore

def test_concurrent_access():
    with tempfile.NamedTemporaryFile() as f:
        store = EventStore(f.name)
        
        def worker():
            for i in range(100):
                store.upsert(Event(...))
                store.get_by_fingerprint(...)
        
        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)  # Should complete quickly
            assert not t.is_alive(), "Thread hung - likely deadlock"
```

## Verification

After fixing:

1. **All tests pass without timeout**:
   ```bash
   pytest tests/ -v --timeout=30
   ```

2. **Quick deadlock test passes**:
   ```bash
   timeout 10 python -c "from module import Store; s = Store(':memory:'); s.upsert(...)"
   ```

3. **Concurrent stress test passes** (see above)

## Pitfalls

- **Don't use RLock as a band-aid** - it can hide architectural issues
- **Lock granularity** - holding lock too long hurts performance; too short causes races
- **Commit inside lock** - always commit while holding the lock, or use WAL mode
- **Connection per thread** - alternative pattern, but complicates connection pooling

## References

- Python threading docs: https://docs.python.org/3/library/threading.html
- SQLite threading modes: https://www.sqlite.org/threadsafe.html
- WAL mode for better concurrency: https://www.sqlite.org/wal.html
