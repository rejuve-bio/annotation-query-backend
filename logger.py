import os
import logging
from pathlib import Path
import axiom_py
from axiom_py.logging import AxiomHandler
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration
from dotenv import load_dotenv
from logging.handlers import RotatingFileHandler

load_dotenv()

def init_logging():
    # Create logs directory for file logging
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    
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

    # --- Create formatter first ---
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # --- Console handler ---
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # --- Axiom ---
    client = axiom_py.Client()
    dataset_name = os.getenv("AXIOM_DATASET", "application-logs")  # configurable
    axiom_handler = AxiomHandler(client, dataset_name)

    # --- Root logger ---
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Add handlers
    root_logger.addHandler(axiom_handler)
    
   # File Handler for Promtail
    app_log_file = logs_dir / "annotation-app.log"
    file_handler = RotatingFileHandler(
        app_log_file,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    
    # Optional: also log to console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    # Add ALL handlers  
    root_logger.addHandler(axiom_handler)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # --- Performance logger ---
    PERF_LOGS_DATASET = os.getenv("AXIOM_PERFORMANCE_LOGS", "performance-metrics")
    perf_handler = AxiomHandler(client, PERF_LOGS_DATASET)
    
    perf_logger = logging.getLogger("performance")
    perf_logger.setLevel(logging.INFO)
    perf_logger.addHandler(perf_handler)
    perf_logger.addHandler(console_handler)
    
    # Add file handler to performance logger
    perf_log_file = logs_dir / "annotation-performance.log"
    perf_file_handler = RotatingFileHandler(
        perf_log_file,
        maxBytes=10*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    perf_file_handler.setFormatter(formatter)
    perf_logger.addHandler(perf_file_handler)
    
    return perf_logger