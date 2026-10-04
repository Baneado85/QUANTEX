from celery import Celery
from app.core.config import settings

# Crear Celery app
celery_app = Celery(
    "quantex",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.services.strategy_runner"],
)

# Configuración
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_send_sent_event=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    broker_connection_retry_on_startup=True,
    # Colores
    task_queues={
        "strategies": {
            "exchange": "celery",
            "routing_key": "strategies",
        },
        "backtests": {
            "exchange": "celery",
            "routing_key": "backtests",
        },
    },
    task_default_queue="strategies",
    task_default_exchange="celery",
    task_default_routing_key="strategies",
)

# Tareas periódicas (beat schedule)
celery_app.conf.beat_schedule = {
    "run-active-strategies-every-1h": {
        "task": "app.services.strategy_runner.run_all_active_strategies",
        "schedule": 3600.0,  # cada hora
        "args": (),
    },
    "run-active-strategies-every-30min": {
        "task": "app.services.strategy_runner.run_all_active_strategies",
        "schedule": 1800.0,  # cada 30 minutos
        "args": (),
    },
}