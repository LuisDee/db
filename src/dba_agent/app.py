from __future__ import annotations

import signal
import threading
import time

from dba_agent.config import load_config
from dba_agent.health import start_health_server
from dba_agent.logging_setup import configure_logging


def main() -> None:
    config = load_config()
    logger = configure_logging(config.log_level, secrets=config.secrets())
    logger.info("dba-agent starting: environment=%s", config.environment)

    server = start_health_server(port=8080)
    logger.info("healthcheck listening on :8080/healthz")

    stop = threading.Event()
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())

    try:
        while not stop.is_set():
            time.sleep(1)
    finally:
        logger.info("shutting down")
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
