from aic2026.api import create_app
from .settings import BackendRuntimeSettings

runtime_settings = BackendRuntimeSettings.from_environment()
app = create_app(
    runtime_settings.run_id,
    runtime_settings.config_path,
    cors_origins=runtime_settings.cors_origins,
)
