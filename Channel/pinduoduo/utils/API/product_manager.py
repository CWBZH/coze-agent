from ...product_parser import parse_product_detail, parse_product_list
from ..base_request import BaseRequest


class ProductManager(BaseRequest):
    """
    拼多多商品管理API
    提供商品列表查询和商品详情获取功能
    """

    def __init__(self, shop_id: str = None, user_id: str = None, cookies=None):
        """
        初始化商品管理器

        Args:
            shop_id: 店铺ID，用于从数据库获取cookies
            user_id: 用户ID，用于从数据库获取cookies
            cookies: 登录cookies，如果直接传入则不需要从数据库获取
        """
        super().__init__(shop_id=shop_id, user_id=None if cookies else user_id)
        self.user_id = user_id
        if cookies:
            self.update_cookies(cookies)

    def get_product_list(self, page=1, size=10):
        """
        获取店铺商品列表

        Args:
            page (int): 页码，默认1
            size (int): 每页数量，默认10

        Returns:
            dict: 商品列表结果，格式如下：
                {
                    "success": True/False,
                    "products": [
                        {
                            "goods_id": int,
                            "goods_name": str,
                            "thumb_url": str,       # 商品缩略图
                            "price": float,         # 价格
                            "sold_quantity": int,   # 已售数量
                            "goods_type": int,      # 商品类型
                            "tag": str,             # 商品标签
                        },
                        ...
                    ],
                    "total": int,  # 总数量
                    "page": int,   # 当前页码
                    "error_msg": str  # 仅在失败时包含
                }
        """
        urls = [
            "https://mms.pinduoduo.com/latitude/goods/queryGoods",
            "https://mms.pinduoduo.com/latitude/goods/recommendGoods",
        ]

        # 构建请求数据
        data = {
            "pageNo": page,
            "pageSize": size,
            "status": 1
        }

        # 构建请求头（与浏览器请求完全一致）
        # anti-content 从 cookies 中获取（由后端动态生成）
        anti_content = self.cookies.get('anti_content') or self.cookies.get('anti-content', '')
        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "anti-content": anti_content,
            "content-type": "application/json;charset=UTF-8",
            "origin": "https://mms.pinduoduo.com",
            "priority": "u=1, i",
            "referer": "https://mms.pinduoduo.com/chat-merchant/index.html",
            "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        }

        last_result = None
        for index, url in enumerate(urls):
            result = self.post(url, json_data=data, headers=headers)
            last_result = result
            if result and result.get("success") is True:
                products_data = parse_product_list(result)
                products = products_data.get("products", [])
                total = products_data.get("total", 0)
                # Try the legacy endpoint before accepting an empty list. PDD
                # changes list payload shapes more often than detail payloads.
                if products or index == len(urls) - 1:
                    return {
                        "success": True,
                        "products": products,
                        "total": total,
                        "page": page,
                        "raw_response": result,
                    }

        error_msg = (last_result.get('errorMsg') or last_result.get('error_msg')) if last_result else "获取商品列表失败"
        self.logger.error(f"获取商品列表失败: {error_msg}")
        return {
            "success": False,
            "error_msg": error_msg,
            "products": [],
            "total": 0,
            "page": page
        }

    def get_product_detail(self, goods_id):
        """
        根据商品ID获取商品详细信息

        Args:
            goods_id (int): 商品ID

        Returns:
            dict: 商品详情结果，格式如下：
                {
                    "success": True/False,
                    "product_info": {
                        "goods_id": int,
                        "goods_name": str,
                        "specifications": str/dict,
                        "price": float,
                        "description": str,
                        # TODO: 根据实际API响应添加更多字段
                    },
                    "error_msg": str  # 仅在失败时包含
                }
        """
        if not goods_id:
            self.logger.error("商品ID不能为空")
            return {"success": False, "error_msg": "商品ID不能为空"}

        # 构建请求URL
        url = "https://mms.pinduoduo.com/glide/v2/mms/query/commit/on_shop/detail"

        # 构建请求数据
        data = {"goods_id": goods_id}

        # 构建请求头，添加anti-content
        anti_content = self.cookies.get('anti_content') or self.cookies.get('anti-content', '')
        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "anti-content": anti_content,
            "content-type": "application/json;charset=UTF-8",
            "origin": "https://mms.pinduoduo.com",
            "referer": "https://mms.pinduoduo.com/chat-merchant/index.html",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        }

        # 发起请求
        result = self.post(url, json_data=data, headers=headers)

        if result and result.get("success") == True:
            # 解析商品详细信息
            product_info = parse_product_detail(result)
            return {
                "success": True,
                "product_info": product_info,
                "raw_response": result,
            }
        else:
            error_msg = result.get('errorMsg') if result else "获取商品详情失败"
            self.logger.error(f"获取商品详情失败 (goods_id={goods_id}): {error_msg}")
            return {
                "success": False,
                "error_msg": error_msg
            }

    def _parse_product_list(self, response_data):
        """
        解析商品列表响应数据

        Args:
            response_data (dict): API响应数据

        Returns:
            dict: 解析后的商品列表数据
        """
        try:
            return parse_product_list(response_data)

        except Exception as e:
            self.logger.error(f"解析商品列表失败: {str(e)}")
            return {
                "products": [],
                "total": 0
            }

    @staticmethod
    def _price_to_cent(value):
        if value is None or value == "":
            return None
        try:
            text = str(value)
            if "." in text:
                return int(round(float(text) * 100))
            return int(value)
        except Exception:
            return None

    @classmethod
    def _format_price(cls, value):
        cents = cls._price_to_cent(value)
        if cents is None:
            return str(value)
        return f"{cents / 100:.2f}"

    def _parse_product_detail(self, response_data):
        """
        解析商品详情响应数据

        Args:
            response_data (dict): API响应数据

        Returns:
            dict: 解析后的商品详情
        """
        try:
            return parse_product_detail(response_data)

        except Exception as e:
            self.logger.error(f"解析商品详情失败: {str(e)}")
            return {
                "goods_id": None,
                "goods_name": "解析失败",
                "specifications": []
            }
