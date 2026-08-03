"""Entry point for the stand-alone ingestion worker process.

Runs indefinitely, polling Redis for ingestion jobs (BLPOP pattern).
Gracefully shuts down on SIGTERM.
"""
from __future__ import annotations

import asyncio
import signal
import sys

from src.infrastructure.ingestion_worker import request_shutdown, run_worker
from src.infrastructure.logging_config import configure_logging, get_logger

if __name__ == "__main__":
    configure_logging(log_level="INFO")
    logger = get_logger("ingestion-worker")

    logger.info("Starting ingestion worker (standalone)")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    worker_task = loop.create_task(run_worker())

    if sys.platform == "win32":
        try:
            signal.signal(signal.SIGBREAK, lambda _s, _f: request_shutdown())  # type: ignore[attr-defined]
        except AttributeError:
            pass
    else:
        loop.add_signal_handler(signal.SIGTERM, request_shutdown)
        loop.add_signal_handler(signal.SIGINT, request_shutdown)

    try:
        loop.run_until_complete(worker_task)
    except KeyboardInterrupt:
        pass
    finally:
        worker_task.cancel()
        try:
            loop.run_until_complete(worker_task)
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass
        loop.close()
        logger.info("Ingestion worker exited")
