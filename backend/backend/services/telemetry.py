"""
OpenTelemetry Configuration Service.

Provides centralized setup for distributed tracing and metrics:
- OTLP exporter to Jaeger
- FastAPI automatic instrumentation
- SQLAlchemy automatic instrumentation
- HTTPX automatic instrumentation
- Custom span creation utilities
"""

import os
import logging
from typing import Optional
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# OpenTelemetry imports with graceful fallback
try:
    from opentelemetry import trace, metrics
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    OTEL_AVAILABLE = True
except ImportError as e:
    logger.warning(f"OpenTelemetry not available: {e}")
    OTEL_AVAILABLE = False
    # Define stub types for when OpenTelemetry is not available
    Resource = None
    SERVICE_NAME = None
    SERVICE_VERSION = None
    TracerProvider = None
    MeterProvider = None


class TelemetryConfig:
    """
    OpenTelemetry configuration manager.

    Handles initialization of tracing and metrics exporters.
    """

    def __init__(
        self,
        service_name: str = "ai-louie-backend",
        service_version: str = "1.0.0",
        otlp_endpoint: Optional[str] = None,
        enable_tracing: bool = True,
        enable_metrics: bool = True,
    ):
        """
        Initialize OpenTelemetry configuration.

        Args:
            service_name: Name of the service
            service_version: Version of the service
            otlp_endpoint: OTLP collector endpoint (e.g., "http://jaeger:4317")
            enable_tracing: Whether to enable distributed tracing
            enable_metrics: Whether to enable OTLP metrics export
        """
        self.service_name = service_name
        self.service_version = service_version
        self.otlp_endpoint = otlp_endpoint or os.getenv("OTLP_ENDPOINT", "http://jaeger:4317")
        self.enable_tracing = enable_tracing and OTEL_AVAILABLE
        self.enable_metrics = enable_metrics and OTEL_AVAILABLE
        self.tracer_provider: Optional[TracerProvider] = None
        self.meter_provider: Optional[MeterProvider] = None

    def setup(self):
        """Initialize OpenTelemetry providers and exporters."""
        if not OTEL_AVAILABLE:
            logger.warning("OpenTelemetry not available - skipping telemetry setup")
            return

        # Create resource with service metadata
        resource = Resource.create({
            SERVICE_NAME: self.service_name,
            SERVICE_VERSION: self.service_version,
            "deployment.environment": os.getenv("ENVIRONMENT", "development"),
        })

        # Setup tracing
        if self.enable_tracing:
            self._setup_tracing(resource)

        # Setup metrics
        if self.enable_metrics:
            self._setup_metrics(resource)

        logger.info(
            f"OpenTelemetry initialized - "
            f"Service: {self.service_name}, "
            f"OTLP Endpoint: {self.otlp_endpoint}, "
            f"Tracing: {self.enable_tracing}, "
            f"Metrics: {self.enable_metrics}"
        )

    def _setup_tracing(self, resource: Resource):
        """Setup distributed tracing with OTLP exporter."""
        try:
            # Create OTLP span exporter
            otlp_exporter = OTLPSpanExporter(
                endpoint=self.otlp_endpoint,
                insecure=True,  # Use insecure for local development
            )

            # Create tracer provider with batch processor
            self.tracer_provider = TracerProvider(resource=resource)
            self.tracer_provider.add_span_processor(
                BatchSpanProcessor(otlp_exporter)
            )

            # Set global tracer provider
            trace.set_tracer_provider(self.tracer_provider)

            logger.info(f"Tracing enabled - exporting to {self.otlp_endpoint}")

        except Exception as e:
            logger.error(f"Failed to setup tracing: {e}", exc_info=True)

    def _setup_metrics(self, resource: Resource):
        """Setup metrics export with OTLP exporter."""
        try:
            # Create OTLP metric exporter
            otlp_metric_exporter = OTLPMetricExporter(
                endpoint=self.otlp_endpoint,
                insecure=True,
            )

            # Create metric reader with periodic export
            metric_reader = PeriodicExportingMetricReader(
                otlp_metric_exporter,
                export_interval_millis=60000,  # Export every 60 seconds
            )

            # Create meter provider
            self.meter_provider = MeterProvider(
                resource=resource,
                metric_readers=[metric_reader],
            )

            # Set global meter provider
            metrics.set_meter_provider(self.meter_provider)

            logger.info(f"Metrics enabled - exporting to {self.otlp_endpoint}")

        except Exception as e:
            logger.error(f"Failed to setup metrics: {e}", exc_info=True)

    def instrument_fastapi(self, app):
        """
        Automatically instrument FastAPI application.

        Args:
            app: FastAPI application instance
        """
        if not OTEL_AVAILABLE or not self.enable_tracing:
            return

        try:
            FastAPIInstrumentor.instrument_app(app)
            logger.info("FastAPI instrumentation enabled")
        except Exception as e:
            logger.error(f"Failed to instrument FastAPI: {e}", exc_info=True)

    def instrument_sqlalchemy(self, engine):
        """
        Automatically instrument SQLAlchemy engine.

        Args:
            engine: SQLAlchemy engine instance
        """
        if not OTEL_AVAILABLE or not self.enable_tracing:
            return

        try:
            SQLAlchemyInstrumentor().instrument(engine=engine)
            logger.info("SQLAlchemy instrumentation enabled")
        except Exception as e:
            logger.error(f"Failed to instrument SQLAlchemy: {e}", exc_info=True)

    def instrument_httpx(self):
        """Automatically instrument HTTPX client."""
        if not OTEL_AVAILABLE or not self.enable_tracing:
            return

        try:
            HTTPXClientInstrumentor().instrument()
            logger.info("HTTPX instrumentation enabled")
        except Exception as e:
            logger.error(f"Failed to instrument HTTPX: {e}", exc_info=True)

    def shutdown(self):
        """Shutdown telemetry providers and flush remaining spans/metrics."""
        if self.tracer_provider:
            try:
                self.tracer_provider.shutdown()
                logger.info("Tracer provider shutdown complete")
            except Exception as e:
                logger.error(f"Error shutting down tracer provider: {e}")

        if self.meter_provider:
            try:
                self.meter_provider.shutdown()
                logger.info("Meter provider shutdown complete")
            except Exception as e:
                logger.error(f"Error shutting down meter provider: {e}")


# Global telemetry configuration
_telemetry_config: Optional[TelemetryConfig] = None


def get_telemetry_config() -> Optional[TelemetryConfig]:
    """Get the global telemetry configuration."""
    return _telemetry_config


def init_telemetry(
    service_name: str = "ai-louie-backend",
    service_version: str = "1.0.0",
    otlp_endpoint: Optional[str] = None,
    enable_tracing: bool = True,
    enable_metrics: bool = True,
) -> TelemetryConfig:
    """
    Initialize global telemetry configuration.

    Args:
        service_name: Service identifier
        service_version: Service version
        otlp_endpoint: OTLP collector endpoint
        enable_tracing: Enable distributed tracing
        enable_metrics: Enable OTLP metrics

    Returns:
        TelemetryConfig instance
    """
    global _telemetry_config

    if _telemetry_config is not None:
        logger.warning("Telemetry already initialized")
        return _telemetry_config

    _telemetry_config = TelemetryConfig(
        service_name=service_name,
        service_version=service_version,
        otlp_endpoint=otlp_endpoint,
        enable_tracing=enable_tracing,
        enable_metrics=enable_metrics,
    )

    _telemetry_config.setup()

    return _telemetry_config


def shutdown_telemetry():
    """Shutdown global telemetry configuration."""
    global _telemetry_config

    if _telemetry_config:
        _telemetry_config.shutdown()
        _telemetry_config = None


# Span creation utilities
@contextmanager
def create_span(name: str, attributes: Optional[dict] = None):
    """
    Create a custom span for manual instrumentation.

    Usage:
        with create_span("my_operation", {"key": "value"}):
            # Your code here
            pass

    Args:
        name: Span name
        attributes: Optional span attributes
    """
    if not OTEL_AVAILABLE:
        yield
        return

    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        yield span
