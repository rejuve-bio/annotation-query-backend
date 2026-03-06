import os
import logging
from logging.handlers import RotatingFileHandler
import axiom_py
from axiom_py.logging import AxiomHandler
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration
from dotenv import load_dotenv

load_dotenv()

def init_logging():
    # Create logfiles directory
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    
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
    client = axiom_py.Client()
    dataset_name = os.getenv("AXIOM_DATASET", "application-logs")  # configurable
    axiom_handler = AxiomHandler(client, dataset_name)

    # --- File Handler for Application Logs ---
    app_file_handler = RotatingFileHandler(
        os.path.join(log_dir, "application.log"),
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    app_file_handler.setLevel(logging.INFO)
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    app_file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Add handlers
    root_logger.addHandler(axiom_handler)
    root_logger.addHandler(app_file_handler)

    # Optional: also log to console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)
    
    # --- Performance Logs ---
    PERF_LOGS_DATASET = os.getenv("AXIOM_PERFORMANCE_LOGS", "performance-metrics")
    perf_handler = AxiomHandler(client, PERF_LOGS_DATASET)
    
    # --- File Handler for Performance Logs ---
    perf_file_handler = RotatingFileHandler(
        os.path.join(log_dir, "performance.log"),
        maxBytes=10*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    perf_file_handler.setLevel(logging.INFO)
    perf_file_handler.setFormatter(formatter)
    
    # --- Performance logger ---
    perf_logger = logging.getLogger("performance")
    perf_logger.setLevel(logging.INFO)
    perf_logger.addHandler(perf_handler)
    perf_logger.addHandler(perf_file_handler)  # Add file handler
    perf_logger.addHandler(console_handler)
    
    return perf_logger