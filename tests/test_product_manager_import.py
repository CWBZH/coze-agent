def test_product_manager_imports_without_core_logger_cycle():
    from Channel.pinduoduo.utils.API.product_manager import ProductManager

    assert ProductManager.__name__ == "ProductManager"
