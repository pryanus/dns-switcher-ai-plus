"""Ограниченные параллельные проверки с кооперативной отменой."""
import socket
import time
from queue import Queue, Empty
from threading import Event, Lock, Thread


class Cancelled(Exception):
    pass


class Cancellation:
    def __init__(self):
        self.event = Event()
        self._lock = Lock()
        self._sockets = set()

    def check(self):
        if self.event.is_set():
            raise Cancelled()

    def track(self, sock):
        with self._lock:
            self.check()
            self._sockets.add(sock)
        return sock

    def untrack(self, sock):
        with self._lock:
            self._sockets.discard(sock)

    def cancel(self):
        self.event.set()
        with self._lock:
            sockets = list(self._sockets)
        for sock in sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass


def parallel(items, function, cancellation=None, timeout=5.0, limit=6):
    """Возвращает результаты в исходном порядке; зависший DNS не держит GUI/выход."""
    items = list(items)
    if not items:
        return []
    token = cancellation or Cancellation()
    pending, completed = Queue(), Queue()
    for index, item in enumerate(items):
        pending.put((index, item))
    results = [None] * len(items)
    expired = Event()

    def run():
        while not token.event.is_set() and not expired.is_set():
            try:
                index, item = pending.get_nowait()
            except Empty:
                return
            try:
                value = function(item)
            except Exception:
                value = None
            completed.put((index, value))

    for _ in range(min(limit, len(items))):
        Thread(target=run, daemon=True).start()
    deadline = None if timeout is None else time.monotonic() + timeout
    count = 0
    try:
        while count < len(items):
            token.check()
            remaining = 0.03 if deadline is None else deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                index, value = completed.get(timeout=min(.03, remaining))
            except Empty:
                continue
            results[index] = value
            count += 1
    finally:
        expired.set()
    return results
