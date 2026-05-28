from __future__ import annotations

from web_api.errors import ApiError


def is_temporary_shop_id(shop_id: str | None) -> bool:
    return bool(str(shop_id or "").startswith("remote-"))


def assert_real_shop_id_bound(shop_id: str | None) -> None:
    if not shop_id or is_temporary_shop_id(shop_id):
        raise shop_id_not_bound_error()


def shop_id_not_bound_error() -> ApiError:
    return ApiError(
        error_type="SHOP_ID_NOT_BOUND",
        error_summary="授权已完成，但尚未绑定真实 PDD 店铺 ID，不能作为正式业务店铺使用。",
        status_code=409,
        retryable=False,
        next_action="请先通过店铺信息或商品同步只读接口解析并绑定真实店铺 ID 后再继续。",
    )

