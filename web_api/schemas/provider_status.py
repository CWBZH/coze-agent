from pydantic import BaseModel, Field


class ProviderState(BaseModel):
    configured: bool = False
    env_keys_present: list[str] = Field(default_factory=list)
    status: str = "config_missing"
    safe_display: dict[str, str] = Field(default_factory=dict)
    error_type: str | None = None


class ProviderStatusResponse(BaseModel):
    engine: str = "internal"
    no_send: bool = True
    providers: dict[str, ProviderState]
    warnings: list[str] = Field(default_factory=list)
