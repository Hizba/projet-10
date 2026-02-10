"""
Configuration centralisée du logging pour Fly Me Chatbot
Supporte Google Cloud Logging et OpenTelemetry pour Cloud Trace
"""

import logging
import logging.config
import os
import sys
from pythonjsonlogger import jsonlogger
import google.cloud.logging
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.semconv.resource import ResourceAttributes


class GoogleCloudLoggingConfig:
    """Configuration pour Google Cloud Logging et OpenTelemetry"""
    
    def __init__(
        self,
        service_name: str = "fly-me-chatbot",
        service_version: str = "1.0",
        log_level: str = "INFO",
        environment: str = "production"
    ):
        self.service_name = service_name
        self.service_version = service_version
        self.log_level = getattr(logging, log_level.upper())
        self.environment = environment
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        
    def setup_cloud_logging(self) -> logging.Logger:
        """Configure Google Cloud Logging avec format structuré"""
        try:
            # Initialiser le client Cloud Logging
            client = google.cloud.logging.Client(project=self.project_id)
            
            # Configurer le handler
            handler = client.get_default_handler()
            handler.setLevel(self.log_level)
            
            # Créer un formateur JSON personnalisé
            log_format = "%(asctime)s %(name)s %(levelname)s %(message)s"
            formatter = jsonlogger.JsonFormatter(
                log_format,
                datefmt="%Y-%m-%dT%H:%M:%SZ"
            )
            handler.setFormatter(formatter)
            
            # Configurer le root logger
            root_logger = logging.getLogger()
            root_logger.setLevel(self.log_level)
            
            # Supprimer les handlers existants pour éviter les doublons
            root_logger.handlers.clear()
            root_logger.addHandler(handler)
            
            # Ajouter un handler console pour le développement local
            if self.environment == "development":
                console_handler = logging.StreamHandler(sys.stdout)
                console_handler.setLevel(logging.DEBUG)
                console_handler.setFormatter(formatter)
                root_logger.addHandler(console_handler)
            
            logging.info(
                "Google Cloud Logging configuré",
                extra={
                    'service_name': self.service_name,
                    'environment': self.environment,
                    'project_id': self.project_id
                }
            )
            
            return root_logger
            
        except Exception as e:
            # Fallback sur logging standard si Cloud Logging échoue
            logging.basicConfig(
                level=self.log_level,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                handlers=[logging.StreamHandler(sys.stdout)]
            )
            logging.warning(f"Impossible de configurer Cloud Logging: {e}")
            logging.info("Utilisation du logging standard Python")
            return logging.getLogger()
    
    def setup_cloud_trace(self) -> trace.Tracer:
        """Configure OpenTelemetry avec Cloud Trace exporter"""
        try:
            # Définir les métadonnées du service
            resource = Resource.create({
                ResourceAttributes.SERVICE_NAME: self.service_name,
                ResourceAttributes.SERVICE_VERSION: self.service_version,
                ResourceAttributes.DEPLOYMENT_ENVIRONMENT: self.environment,
                "gcp.project_id": self.project_id
            })
            
            # Configurer le tracer provider
            tracer_provider = TracerProvider(resource=resource)
            
            # Ajouter l'exporteur Cloud Trace
            cloud_trace_exporter = CloudTraceSpanExporter(project_id=self.project_id)
            tracer_provider.add_span_processor(
                BatchSpanProcessor(cloud_trace_exporter)
            )
            
            # Définir le tracer provider global
            trace.set_tracer_provider(tracer_provider)
            
            logging.info(
                "OpenTelemetry Cloud Trace configuré",
                extra={'service_name': self.service_name}
            )
            
            return trace.get_tracer(self.service_name)
            
        except Exception as e:
            logging.warning(f"Impossible de configurer Cloud Trace: {e}")
            # Retourner un tracer par défaut (no-op)
            return trace.get_tracer(self.service_name)


# ✨ Filtre pour masquer les données sensibles
class SensitiveDataFilter(logging.Filter):
    """Filtre pour masquer les données sensibles dans les logs"""
    
    import re
    
    # Patterns pour identifier les données sensibles
    PATTERNS = {
        'credit_card': re.compile(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b'),
        'email': re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
        'api_key': re.compile(r'(api[_-]?key|apikey|token)[\s:=]+[\w\-]+', re.IGNORECASE)
    }
    
    def filter(self, record):
        """Masquer les données sensibles dans le message de log"""
        if isinstance(record.msg, str):
            for pattern_name, pattern in self.PATTERNS.items():
                record.msg = pattern.sub('[REDACTED]', record.msg)
        return True


# ✨ Configuration dictConfig (alternative)
def get_logging_dict_config(environment: str = "production") -> dict:
    """
    Retourne une configuration dictConfig pour logging.config.dictConfig()
    Alternative à la classe GoogleCloudLoggingConfig
    """
    log_level = "DEBUG" if environment == "development" else "INFO"
    
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "sensitive_data_filter": {
                "()": SensitiveDataFilter,
            }
        },
        "formatters": {
            "json": {
                "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
                "datefmt": "%Y-%m-%dT%H:%M:%SZ",
                "class": "pythonjsonlogger.jsonlogger.JsonFormatter",
            },
            "standard": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "json",
                "filters": ["sensitive_data_filter"],
                "level": log_level
            }
        },
        "loggers": {
            "": {  # Root logger
                "handlers": ["console"],
                "level": log_level
            },
            "fly_me": {  # Logger spécifique à l'application
                "handlers": ["console"],
                "level": log_level,
                "propagate": False
            },
            "uvicorn": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False
            }
        }
    }


# ✨ Fonction d'initialisation simple
def init_logging(
    service_name: str = "fly-me-chatbot",
    environment: str = None
) -> tuple[logging.Logger, trace.Tracer]:
    """
    Initialise le logging et le tracing
    
    Args:
        service_name: Nom du service
        environment: Environnement (production/development)
    
    Returns:
        Tuple (logger, tracer)
    """
    if environment is None:
        environment = os.getenv("ENVIRONMENT", "production")
    
    config = GoogleCloudLoggingConfig(
        service_name=service_name,
        environment=environment,
        log_level=os.getenv("LOG_LEVEL", "INFO")
    )
    
    logger = config.setup_cloud_logging()
    tracer = config.setup_cloud_trace()
    
    return logger, tracer


# ✨ Fonction helper pour créer des loggers par module
def get_logger(name: str) -> logging.Logger:
    """
    Retourne un logger pour un module spécifique
    
    Usage:
        logger = get_logger(__name__)
    """
    return logging.getLogger(name)
