from utils.pdd_send_policy import is_pdd_sending_enabled, pdd_sending_status
from web_api.schemas.ai_settings import AiSettings, AiSettingsUpdate


class AiSettingsService:
    def __init__(self) -> None:
        self._settings: dict[str, AiSettings] = {}

    def get_settings(self, shop_id: str) -> AiSettings:
        if shop_id not in self._settings:
            self._settings[shop_id] = AiSettings(shop_id=shop_id)
        current = self._settings[shop_id].model_copy(deep=True)
        pdd_enabled = is_pdd_sending_enabled()
        current.send_enabled = bool(current.send_enabled and pdd_enabled)
        current.no_send_mode = not current.send_enabled
        current.secret_status.pdd_sending = pdd_sending_status()
        self._settings[shop_id] = current
        return current

    def update_settings(self, shop_id: str, update: AiSettingsUpdate) -> AiSettings:
        current = self.get_settings(shop_id).model_copy(deep=True)
        data = update.model_dump(exclude_unset=True)
        warning = None
        pdd_enabled = is_pdd_sending_enabled()
        if data.get("send_enabled") is True and not pdd_enabled:
            data["send_enabled"] = False
            warning = "PDD 真实发送未启用：需要配置 PDD_SENDING_ENABLED=true 后才能开启发送。"
        for key, value in data.items():
            setattr(current, key, value)
        current.send_enabled = bool(current.send_enabled and pdd_enabled)
        current.no_send_mode = not current.send_enabled
        current.secret_status.pdd_sending = pdd_sending_status()
        current.warning = warning
        self._settings[shop_id] = current
        return current
