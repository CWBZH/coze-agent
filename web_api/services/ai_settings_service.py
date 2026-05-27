from web_api.schemas.ai_settings import AiSettings, AiSettingsUpdate


class AiSettingsService:
    def __init__(self) -> None:
        self._settings: dict[str, AiSettings] = {}

    def get_settings(self, shop_id: str) -> AiSettings:
        if shop_id not in self._settings:
            self._settings[shop_id] = AiSettings(shop_id=shop_id)
        return self._settings[shop_id]

    def update_settings(self, shop_id: str, update: AiSettingsUpdate) -> AiSettings:
        current = self.get_settings(shop_id).model_copy(deep=True)
        data = update.model_dump(exclude_unset=True)
        warning = None
        if data.get("send_enabled") is True:
            data["send_enabled"] = False
            warning = "real PDD sending is disabled in MVP"
        for key, value in data.items():
            setattr(current, key, value)
        current.no_send_mode = True
        current.send_enabled = False
        current.warning = warning
        self._settings[shop_id] = current
        return current
