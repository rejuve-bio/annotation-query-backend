import os
import logging
import logging.handlers
from pathlib import Path

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

    # --- Axiom ---
    client = axiom_py.Client()
    dataset_name = os.getenv("AXIOM_DATASET", "application-logs")  # configurable
    axiom_handler = AxiomHandler(client, dataset_name)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # File Handler for Promtail
    app_log_file = logs_dir / "annotation-app.log"
    file_handler = logging.handlers.RotatingFileHandler(
        app_log_file,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    
    # Formatter for file logs (similar to console)
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    # Add ALL handlers (Axiom + File + Console)
    root_logger.addHandler(axiom_handler)
    root_logger.addHandler(file_handler)    # For Promtail scraping
    root_logger.addHandler(console_handler)

    # Optional: also log to console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    PERF_LOGS_DATASET = os.getenv("AXIOM_PERFORMANCE_LOGS", "performance-metrics")
    perf_handler = AxiomHandler(client, PERF_LOGS_DATASET)
    
    # --- Performance logger ---
    perf_logger = logging.getLogger("performance")
    perf_logger.setLevel(logging.INFO)
    perf_logger.addHandler(perf_handler)
    perf_logger.addHandler(console_handler)
    
    # NEW: Also add file handler to performance logger
    perf_log_file = logs_dir / "annotation-performance.log"
    perf_file_handler = logging.handlers.RotatingFileHandler(
        perf_log_file,
        maxBytes=10*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    perf_file_handler.setFormatter(formatter)
    perf_logger.addHandler(perf_file_handler)
    
    return perf_logger