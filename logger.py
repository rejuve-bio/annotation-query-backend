import os
import logging
import axiom_py
from axiom_py.logging import AxiomHandler
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration
from dotenv import load_dotenv

load_dotenv()

def init_logging():
    # --- Sentry ---
    DSN = os.getenv("SENTRY_DSN")
    sentry_logging = LoggingIntegration(
        level=logging.INFO,        # Capture >= INFO as breadcrumbs
        event_level=logging.ERROR  # Send ERROR and above as events
    )

    sentry_sdk.init(
        dsn=DSN,
        integrations=[sentry_logging],
        send_default_pii=True,
        attach_stacktrace=True
    )

    # --- Axiom ---
    axiom_token = os.getenv("AXIOM_TOKEN")
    client = None
    axiom_handler = None
    perf_handler = None
    if axiom_token:
        client = axiom_py.Client()
        dataset_name = os.getenv("AXIOM_DATASET", "application-logs")  # configurable
        axiom_handler = AxiomHandler(client, dataset_name)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Add handlers
    if axiom_handler:
        root_logger.addHandler(axiom_handler)

    # Optional: also log to console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)
    
    PERF_LOGS_DATASET = os.getenv("AXIOM_PERFORMANCE_LOGS", "performance-metrics")
    if client:
        perf_handler = AxiomHandler(client, PERF_LOGS_DATASET)
    
    # --- Performance logger ---
    perf_logger = logging.getLogger("performance")
    perf_logger.setLevel(logging.INFO)
    if perf_handler:
        perf_logger.addHandler(perf_handler)
    perf_logger.addHandler(console_handler)
    
    return perf_logger
