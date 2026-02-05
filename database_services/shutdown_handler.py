"""
Graceful shutdown handling for the sync process.

Provides:
- Signal handlers for SIGINT/SIGTERM
- Thread-safe shutdown state
- Integration with existing shutdown.flag mechanism
"""
import signal
import os
import threading
import sys
from typing import Optional
from datetime import datetime


class ShutdownHandler:
    """Thread-safe shutdown state manager."""

    _instance: Optional['ShutdownHandler'] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._shutdown_requested = False
        self._shutdown_reason: Optional[str] = None
        self._shutdown_time: Optional[datetime] = None
        self._state_lock = threading.Lock()
        self._initialized = True

    def request_shutdown(self, reason: str = "manual"):
        """Request graceful shutdown."""
        with self._state_lock:
            if not self._shutdown_requested:
                self._shutdown_requested = True
                self._shutdown_reason = reason
                self._shutdown_time = datetime.now()
                print(f"\n{'='*60}")
                print(f"SHUTDOWN REQUESTED: {reason}")
                print(f"Time: {self._shutdown_time}")
                print(f"Completing current operation before exit...")
                print(f"{'='*60}\n")

    def is_shutdown_requested(self) -> bool:
        """Check if shutdown has been requested (thread-safe)."""
        with self._state_lock:
            if self._shutdown_requested:
                return True
        # Also check shutdown.flag for backwards compatibility
        return os.path.exists('shutdown.flag')

    @property
    def shutdown_reason(self) -> Optional[str]:
        with self._state_lock:
            return self._shutdown_reason

    @property
    def shutdown_time(self) -> Optional[datetime]:
        with self._state_lock:
            return self._shutdown_time

    def clear(self):
        """Clear shutdown state (for testing or restart)."""
        with self._state_lock:
            self._shutdown_requested = False
            self._shutdown_reason = None
            self._shutdown_time = None


# Global instance
_handler = ShutdownHandler()


def _signal_handler(signum, frame):
    """Handle SIGINT/SIGTERM signals."""
    sig_name = signal.Signals(signum).name
    _handler.request_shutdown(f"Signal {sig_name} ({signum})")


def setup_signal_handlers():
    """
    Register signal handlers for graceful shutdown.

    On Windows, only SIGINT (Ctrl+C) is reliably supported.
    On Unix, both SIGINT and SIGTERM are supported.
    """
    # SIGINT works on all platforms (Ctrl+C)
    signal.signal(signal.SIGINT, _signal_handler)

    # SIGTERM only works on Unix-like systems
    if sys.platform != 'win32':
        signal.signal(signal.SIGTERM, _signal_handler)
        print("Signal handlers registered for SIGINT/SIGTERM")
    else:
        print("Signal handler registered for SIGINT (Ctrl+C)")
        print("Note: On Windows, use shutdown.flag or Ctrl+C for graceful shutdown")


def is_shutdown_requested() -> bool:
    """Check if shutdown requested (convenience function)."""
    return _handler.is_shutdown_requested()


def request_shutdown(reason: str = "manual"):
    """Request shutdown (convenience function)."""
    _handler.request_shutdown(reason)


def get_handler() -> ShutdownHandler:
    """Get the shutdown handler instance."""
    return _handler


def clear_shutdown_state():
    """Clear shutdown state (convenience function)."""
    _handler.clear()
