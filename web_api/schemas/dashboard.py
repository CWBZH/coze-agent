from pydantic import BaseModel


class DashboardMetric(BaseModel):
    key: str
    label: str
    value: str | int | float
    caption: str | None = None


class DashboardAlert(BaseModel):
    time: str | None = None
    level: str
    message: str


class DashboardSummary(BaseModel):
    metrics: list[DashboardMetric]
    alerts: list[DashboardAlert]
    system_status: list[DashboardAlert]
    warning: str | None = None
