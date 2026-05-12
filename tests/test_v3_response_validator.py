"""
Unit tests for V3.0 Response Validator - no LLM calls required.
"""
import pytest
import sys
import importlib.util
from pathlib import Path

# Load response_validator module directly
module_path = Path(__file__).parent.parent / "Agent" / "CustomerAgent" / "custom" / "response_validator.py"
spec = importlib.util.spec_from_file_location("response_validator", module_path)
validator_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator_module)

validate_response = validator_module.validate_response
handle_fallback = validator_module.handle_fallback
ValidationResult = validator_module.ValidationResult


class TestSKUValidation:
    """Test SKU original text preservation."""

    def test_sku_original_text_pass(self):
        """SKU original text preserved should pass."""
        response_text = "有一瓶、2瓶、3瓶三种规格可选。"
        product_json = {
            "sku_summary": "一瓶20ml",
            "sku_options": ["一瓶", "2瓶", "3瓶"]
        }
        user_query = "规格有哪些?"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is True
        assert result.reason == ""

    def test_sku_rewrite_fail(self):
        """SKU rewritten without original should fail."""
        response_text = "有1瓶、两瓶、三瓶三种规格。"
        product_json = {
            "sku_summary": "一瓶20ml",
            "sku_options": ["一瓶", "2瓶", "3瓶"]
        }
        user_query = "规格有哪些?"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is False
        assert "SKU改写" in result.reason
        assert result.fallback_type == "template_uncertain"

    def test_sku_partial_rewrite_fail(self):
        """SKU with one rewritten but another original should fail for rewrite."""
        response_text = "有一瓶、两瓶可选。"
        product_json = {
            "sku_options": ["一瓶", "2瓶"]
        }
        user_query = "有什么规格?"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is False
        assert "SKU改写" in result.reason or "SKU原文缺失" in result.reason

    def test_sku_missing_option_fail(self):
        """Specification query missing SKU option should fail."""
        response_text = "有一瓶、2瓶可选。"
        product_json = {
            "sku_options": ["一瓶", "2瓶", "3瓶"]
        }
        user_query = "规格有哪些?"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is False
        assert "SKU原文缺失" in result.reason

    def test_sku_no_match_empty_options(self):
        """Empty SKU options should pass."""
        response_text = "这是商品介绍。"
        product_json = {
            "sku_summary": "",
            "sku_options": []
        }
        user_query = "介绍一下"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is True


class TestEmptyFieldValidation:
    """Test empty field fabrication detection."""

    def test_empty_field_fabrication_fail(self):
        """Empty field with definite answer should fail."""
        response_text = "这款商品有茉莉香味。"
        product_json = {
            "fragrance": "",
            "shelf_life": ""
        }
        user_query = "有香味吗?"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is False
        assert "空字段编造" in result.reason
        assert result.fallback_type == "template_uncertain"

    def test_empty_field_uncertain_pass(self):
        """Empty field with uncertain expression should pass."""
        response_text = "这个信息我不确定,建议您咨询人工客服。"
        product_json = {
            "fragrance": "",
            "shelf_life": ""
        }
        user_query = "有香味吗?"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is True

    def test_age_12_pass(self):
        """Age question with suitable_age should pass."""
        response_text = "12岁以上能使用这款商品。"
        product_json = {
            "suitable_age": "12岁以上能使用"
        }
        user_query = "12岁可以用吗?"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is True

    def test_pregnancy_unmarked_fail(self):
        """Pregnancy query without pregnancy info should fail without uncertainty."""
        response_text = "孕妇可以使用这款商品。"
        product_json = {
            "suitable_age": "12岁以上能使用"
        }
        user_query = "孕妇能用吗?"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is False
        assert "孕妇" in result.reason
        assert result.fallback_type == "template_uncertain"

    def test_pregnancy_unmarked_uncertain_pass(self):
        """Pregnancy query without pregnancy info should pass with uncertainty."""
        response_text = "关于孕妇使用,这个信息我不确定,建议您咨询人工客服。"
        product_json = {
            "suitable_age": "12岁以上能使用"
        }
        user_query = "孕妇能用吗?"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is True

    def test_pregnancy_marked_pass(self):
        """Pregnancy query with pregnancy info should pass."""
        response_text = "孕妇慎用,建议咨询医生。"
        product_json = {
            "suitable_age": "孕妇慎用,12岁以上能使用"
        }
        user_query = "孕妇能用吗?"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is True

    def test_shelf_life_empty_fail(self):
        """Empty shelf life with definite answer should fail."""
        response_text = "保质期是三年。"
        product_json = {
            "shelf_life": ""
        }
        user_query = "保质期多久?"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is False
        assert "空字段编造" in result.reason


class TestMedicalClaimValidation:
    """Test medical claim detection."""

    def test_medical_claim_fail(self):
        """Medical claim should fail."""
        response_text = "这款喷雾可以治疗狐臭。"
        product_json = {}
        user_query = "能治狐臭吗?"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is False
        assert "医疗承诺" in result.reason
        assert result.fallback_type == "template_risk_medical"

    def test_medical_negation_pass(self):
        """Medical negation should pass."""
        response_text = "这是止汗喷雾,不能替代医疗治疗。"
        product_json = {}
        user_query = "能治狐臭吗?"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is True

    def test_medical_no_capability_pass(self):
        """No medical capability statement should pass."""
        response_text = "这个商品不具备治疗功能,不能治疗疾病。"
        product_json = {}
        user_query = "能治病吗?"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is True


class TestPriceInferenceValidation:
    """Test price inference detection."""

    def test_price_empty_fail(self):
        """Empty price with price claim should fail."""
        response_text = "这个商品大概19.9元,现在优惠15元。"
        product_json = {
            "price": ""
        }
        user_query = "多少钱?"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is False
        assert "价格推断" in result.reason
        assert result.fallback_type == "template_price"

    def test_price_empty_no_inference_pass(self):
        """Empty price without inference should pass."""
        response_text = "请以商品页面实际价格为准。"
        product_json = {
            "price": ""
        }
        user_query = "多少钱?"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is True

    def test_price_present_original_pass(self):
        """Price present with original price should pass."""
        response_text = "价格是4.80-12.00元。"
        product_json = {
            "price": "4.80-12.00"
        }
        user_query = "多少钱?"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is True

    def test_price_present_fabricated_fail(self):
        """Price present but fabricated different price should fail."""
        response_text = "价格是9.9元。"
        product_json = {
            "price": "4.80-12.00"
        }
        user_query = "多少钱?"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is False
        assert "价格编造" in result.reason

    def test_price_comparison_fail(self):
        """Price comparison claim should fail."""
        response_text = "这个商品最划算,性价比最高。"
        product_json = {
            "price": "9.90"
        }
        user_query = "多少钱?"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is False
        assert "价格比较承诺" in result.reason
        assert result.fallback_type == "template_price"

    def test_price_comparison_no_price_fail(self):
        """Comparison claim should fail even without price."""
        response_text = "这个最划算。"
        product_json = {
            "price": ""
        }
        user_query = "几瓶划算?"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is False
        assert "价格比较承诺" in result.reason


class TestHumanRequestDetection:
    """Test human customer service request detection."""

    def test_human_request_detection(self):
        """Human request should be detected."""
        response_text = "正在为您转接人工客服。"
        product_json = {}
        user_query = "转人工"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is False
        assert "人工客服" in result.reason
        assert result.fallback_type == "template_human"

    def test_human_request_variants(self):
        """Human request variants should be detected."""
        response_text = "好的"
        product_json = {}
        user_query = "找人工客服"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is False
        assert result.fallback_type == "template_human"


class TestFaceUseValidation:
    """Test face/face use validation."""

    def test_face_use_unmarked_fail(self):
        """Face use query without face info should fail without uncertainty."""
        response_text = "可以喷脸上。"
        product_json = {
            "usage_method": "出门喷可以持续两至三个小时"
        }
        user_query = "可以喷脸吗?"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is False
        assert "脸部使用未标注" in result.reason

    def test_face_use_unmarked_uncertain_pass(self):
        """Face use query without face info should pass with uncertainty."""
        response_text = "页面暂未标注脸部是否适用。"
        product_json = {
            "usage_method": "出门喷可以持续两至三个小时"
        }
        user_query = "可以喷脸吗?"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is True

    def test_face_use_marked_pass(self):
        """Face use query with face info should pass."""
        response_text = "可以用在面部。"
        product_json = {
            "usage_method": "出门喷脸部可以持续两至三个小时"
        }
        user_query = "可以喷脸吗?"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is True


class TestFallbackHandler:
    """Test fallback template handler."""

    def test_fallback_uncertain(self):
        """Uncertain fallback should return correct template."""
        result = handle_fallback("template_uncertain")
        assert "不确定" in result
        assert "人工客服" in result

    def test_fallback_medical(self):
        """Medical fallback should return correct template."""
        result = handle_fallback("template_risk_medical")
        assert "不是药品" in result
        assert "咨询医生" in result

    def test_fallback_price(self):
        """Price fallback should return correct template."""
        result = handle_fallback("template_price")
        assert "商品页面" in result
        assert "价格" in result

    def test_fallback_human(self):
        """Human fallback should return correct template."""
        result = handle_fallback("template_human")
        assert "转接人工客服" in result

    def test_fallback_unknown_type(self):
        """Unknown fallback type should return uncertain template."""
        result = handle_fallback("unknown_type")
        assert "不确定" in result


class TestValidationIntegration:
    """Integration tests for multiple validation rules."""

    def test_all_pass(self):
        """All validations passing should return valid."""
        response_text = "有一瓶、2瓶规格,价格请以商品页面为准。"
        product_json = {
            "sku_options": ["一瓶", "2瓶"],
            "price": ""
        }
        user_query = "有什么规格?多少钱?"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is True

    def test_priority_human_over_sku(self):
        """Human request should have highest priority."""
        response_text = "有1瓶规格"
        product_json = {
            "sku_options": ["一瓶"]
        }
        user_query = "转人工"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is False
        assert result.fallback_type == "template_human"

    def test_multiple_failures_first_wins(self):
        """First validation failure should be returned."""
        response_text = "有1瓶规格,可以治疗狐臭。"
        product_json = {
            "sku_options": ["一瓶"],
            "price": ""
        }
        user_query = "有什么规格?"

        result = validate_response(response_text, product_json, user_query)

        assert result.valid is False
        # SKU validation runs before medical, so SKU error should be returned
        assert "SKU改写" in result.reason
