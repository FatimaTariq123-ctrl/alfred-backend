import contextlib
import time

@contextlib.contextmanager
def Timer(service, action, metadata=None):
    start = time.time()
    yield
    elapsed = time.time() - start
    print(f"⏱️ [{service}] {action} completed in {elapsed:.3f}s (metadata={metadata})")
