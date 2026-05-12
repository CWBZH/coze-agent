"""Tests for V3 product locator primitive.

Tests cover:
- Platform goods_id priority (confidence 1.0)
- Locked goods_id priority (confidence 0.95)
- Link/text parsing (confidence 0.9)
- Keyword fallback (confidence 0.60-0.85)
- Ambiguous keyword matches
- Chinese product differentiation
- Punctuation/whitespace robustness
"""

import pytest
import importlib.util
from pathlib import Path

# Load product_locator module directly without triggering __init__.py
# This avoids dependency on services that aren't initialized in test context
module_path = (
    Path(__file__).parent.parent
    / "Agent"
    / "CustomerAgent"
    / "custom"
    / "product_locator.py"
)
spec = importlib.util.spec_from_file_location("product_locator", module_path)
product_locator_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(product_locator_module)

ProductCandidate = product_locator_module.ProductCandidate
ProductLocatorResult = product_locator_module.ProductLocatorResult
ProductLocator = product_locator_module.ProductLocator


class TestProductLocatorPriority:
    """Test strict priority ordering."""

    def test_platform_priority_over_locked(self):
        """Platform goods_id takes priority over locked."""
        result = ProductLocator.locate(
            query="",
            platform_goods_id="111111",
            locked_goods_id="222222",
        )
        assert result.goods_id == "111111"
        assert result.confidence == 1.0
        assert result.source == ProductLocator.SOURCE_PLATFORM

    def test_platform_priority_over_link(self):
        """Platform goods_id takes priority over parsed link."""
        result = ProductLocator.locate(
            query="goods_id=333333",
            platform_goods_id="111111",
        )
        assert result.goods_id == "111111"
        assert result.confidence == 1.0
        assert result.source == ProductLocator.SOURCE_PLATFORM

    def test_locked_priority_over_link(self):
        """Locked goods_id takes priority over parsed link."""
        result = ProductLocator.locate(
            query="goods_id=333333",
            locked_goods_id="222222",
        )
        assert result.goods_id == "222222"
        assert result.confidence == 0.95
        assert result.source == ProductLocator.SOURCE_LOCKED

    def test_locked_priority_over_keyword(self):
        """Locked goods_id takes priority over keyword match."""
        result = ProductLocator.locate(
            query="iPhone 15",
            locked_goods_id="222222",
            candidates=[
                ProductCandidate(goods_id="333333", goods_name="iPhone 15", search_terms=["iPhone"])
            ],
        )
        assert result.goods_id == "222222"
        assert result.confidence == 0.95
        assert result.source == ProductLocator.SOURCE_LOCKED


class TestProductLocatorLinkParsing:
    """Test link/text goods_id extraction."""

    def test_goods_id_equals(self):
        """Parse goods_id=123456 format."""
        result = ProductLocator.locate(
            query="https://example.com/product?goods_id=123456",
        )
        assert result.goods_id == "123456"
        assert result.confidence == 0.9
        assert result.source == ProductLocator.SOURCE_LINK

    def test_goods_id_camel_case(self):
        """Parse goodsId=123456 format."""
        result = ProductLocator.locate(
            query="goodsId=654321",
        )
        assert result.goods_id == "654321"
        assert result.confidence == 0.9

    def test_url_encoded(self):
        """Parse URL-encoded goods_id%3D123456."""
        result = ProductLocator.locate(
            query="goods_id%3D789012",
        )
        assert result.goods_id == "789012"
        assert result.confidence == 0.9

    def test_chinese_id_with_colon(self):
        """Parse 商品ID:123456 format."""
        result = ProductLocator.locate(
            query="商品ID:123456",
        )
        assert result.goods_id == "123456"
        assert result.confidence == 0.9

    def test_chinese_id_without_colon(self):
        """Parse 商品id123456 format."""
        result = ProductLocator.locate(
            query="商品id123456",
        )
        assert result.goods_id == "123456"

    def test_invalid_too_short(self):
        """Reject goods_id with fewer than 6 digits."""
        result = ProductLocator.locate(
            query="goods_id=12345",
        )
        assert result.goods_id is None
        assert result.source == ProductLocator.SOURCE_NONE

    def test_invalid_too_long(self):
        """Reject goods_id with more than 20 digits."""
        result = ProductLocator.locate(
            query="goods_id=123456789012345678901",
        )
        assert result.goods_id is None
        assert result.source == ProductLocator.SOURCE_NONE


class TestProductLocatorKeywordMatching:
    """Test keyword fallback matching."""

    def test_full_name_in_query(self):
        """Full goods_name in query scores 0.85."""
        result = ProductLocator.locate(
            query="我想买苹果手机iPhone 15 Pro",
            candidates=[
                ProductCandidate(
                    goods_id="123456",
                    goods_name="苹果手机iPhone 15 Pro",
                    search_terms=["iPhone"],
                )
            ],
        )
        assert result.goods_id == "123456"
        assert result.confidence == 0.85
        assert result.source == ProductLocator.SOURCE_KEYWORD

    def test_query_in_name(self):
        """Query contained in goods_name scores 0.75 (short product mention)."""
        result = ProductLocator.locate(
            query="苹果",
            candidates=[
                ProductCandidate(
                    goods_id="123456",
                    goods_name="苹果手机iPhone 15",
                    search_terms=["iPhone"],
                )
            ],
        )
        assert result.goods_id == "123456"
        assert result.confidence == 0.75
        assert result.source == ProductLocator.SOURCE_KEYWORD

    def test_search_term_matching(self):
        """Each matched search_term adds 0.12 starting from 0.60."""
        result = ProductLocator.locate(
            query="iPhone 手机",
            candidates=[
                ProductCandidate(
                    goods_id="123456",
                    goods_name="苹果手机",
                    search_terms=["iPhone", "手机"],
                )
            ],
        )
        assert result.goods_id == "123456"
        # 2 terms matched: 0.60 + 2 * 0.12 = 0.84
        assert result.confidence == 0.84
        assert result.source == ProductLocator.SOURCE_KEYWORD

    def test_term_score_cap(self):
        """Term score capped at 0.84."""
        result = ProductLocator.locate(
            query="iPhone 手机 苹果",
            candidates=[
                ProductCandidate(
                    goods_id="123456",
                    goods_name="产品",
                    search_terms=["iPhone", "手机", "苹果", "Pro"],
                )
            ],
        )
        assert result.goods_id == "123456"
        # Would be 0.60 + 3 * 0.12 = 0.96, but capped at 0.84
        assert result.confidence == 0.84

    def test_name_score_over_term_score(self):
        """Final score is max(name score, term score)."""
        result = ProductLocator.locate(
            query="苹果手机iPhone",
            candidates=[
                ProductCandidate(
                    goods_id="123456",
                    goods_name="苹果手机",
                    search_terms=["手机"],
                )
            ],
        )
        # Name "苹果手机" in query: 0.85
        # Term "手机" matched: 0.60 + 0.12 = 0.72
        # Final: max(0.85, 0.72) = 0.85
        assert result.goods_id == "123456"
        assert result.confidence == 0.85


class TestProductLocatorAmbiguity:
    """Test ambiguous keyword match handling."""

    def test_ambiguous_equal_scores(self):
        """Tied top scores return none with ambiguous_keyword_match."""
        result = ProductLocator.locate(
            query="iPhone",
            candidates=[
                ProductCandidate(
                    goods_id="111111",
                    goods_name="iPhone 15",
                    search_terms=["iPhone"],
                ),
                ProductCandidate(
                    goods_id="222222",
                    goods_name="iPhone 14",
                    search_terms=["iPhone"],
                ),
            ],
        )
        assert result.goods_id is None
        assert result.source == ProductLocator.SOURCE_NONE
        assert result.reason == "ambiguous_keyword_match"

    def test_unambiguous_different_scores(self):
        """Different top scores return highest."""
        result = ProductLocator.locate(
            query="iPhone 15 Pro",
            candidates=[
                ProductCandidate(
                    goods_id="111111",
                    goods_name="iPhone 15 Pro",
                    search_terms=["iPhone"],
                ),
                ProductCandidate(
                    goods_id="222222",
                    goods_name="Samsung Galaxy",
                    search_terms=["iPhone", "Pro"],
                ),
            ],
        )
        # First candidate: name "iPhone 15 Pro" in query -> 0.85
        # Second candidate: terms "iPhone" + "Pro" matched -> 0.60 + 2*0.12 = 0.84
        # First wins with 0.85 vs 0.84
        assert result.goods_id == "111111"
        assert result.confidence == 0.85


class TestProductLocatorNormalization:
    """Test text normalization for keyword matching."""

    def test_chinese_preserved(self):
        """Chinese characters preserved in normalization."""
        result = ProductLocator.locate(
            query="苹果手机",
            candidates=[
                ProductCandidate(
                    goods_id="123456",
                    goods_name="苹果手机",
                    search_terms=[],
                )
            ],
        )
        assert result.goods_id == "123456"
        assert result.confidence == 0.85

    def test_case_insensitive(self):
        """Normalization lowercases ASCII."""
        result = ProductLocator.locate(
            query="IPHONE 15",
            candidates=[
                ProductCandidate(
                    goods_id="123456",
                    goods_name="iPhone 15",
                    search_terms=[],
                )
            ],
        )
        assert result.goods_id == "123456"
        assert result.confidence == 0.85

    def test_punctuation_removed(self):
        """Punctuation and separators removed."""
        result = ProductLocator.locate(
            query="苹果-手机！",
            candidates=[
                ProductCandidate(
                    goods_id="123456",
                    goods_name="苹果手机",
                    search_terms=[],
                )
            ],
        )
        assert result.goods_id == "123456"
        assert result.confidence == 0.85

    def test_whitespace_removed(self):
        """Whitespace removed in normalization."""
        result = ProductLocator.locate(
            query="苹 果 手 机",
            candidates=[
                ProductCandidate(
                    goods_id="123456",
                    goods_name="苹果手机",
                    search_terms=[],
                )
            ],
        )
        assert result.goods_id == "123456"
        assert result.confidence == 0.85


class TestProductLocatorEdgeCases:
    """Test edge cases and special scenarios."""

    def test_empty_query(self):
        """Empty query returns none."""
        result = ProductLocator.locate(
            query="",
            candidates=[
                ProductCandidate(
                    goods_id="123456",
                    goods_name="iPhone",
                    search_terms=["iPhone"],
                )
            ],
        )
        assert result.goods_id is None
        assert result.source == ProductLocator.SOURCE_NONE

    def test_empty_candidates(self):
        """Empty candidates returns none."""
        result = ProductLocator.locate(
            query="iPhone",
            candidates=[],
        )
        assert result.goods_id is None
        assert result.source == ProductLocator.SOURCE_NONE

    def test_all_none(self):
        """All parameters None returns none."""
        result = ProductLocator.locate(
            query="",
        )
        assert result.goods_id is None
        assert result.confidence == 0.0
        assert result.source == ProductLocator.SOURCE_NONE
        assert "No product match" in result.reason

    def test_chinese_product_differentiation(self):
        """Chinese products with similar names distinguished."""
        result = ProductLocator.locate(
            query="苹果手机Pro版",
            candidates=[
                ProductCandidate(
                    goods_id="111111",
                    goods_name="苹果手机标准版",
                    search_terms=["标准版"],
                ),
                ProductCandidate(
                    goods_id="222222",
                    goods_name="苹果手机Pro版",
                    search_terms=["Pro版"],
                ),
            ],
        )
        assert result.goods_id == "222222"
        assert result.confidence == 0.85


class TestProductLocatorContractCompliance:
    """Test SDD contract compliance."""

    def test_locate_with_no_kwargs(self):
        """locate("hello") can be called with no keyword args and returns None."""
        result = ProductLocator.locate("hello")
        assert result.goods_id is None
        assert result.source == ProductLocator.SOURCE_NONE

    def test_whitespace_platform_goods_id_ignored(self):
        """Whitespace platform_goods_id is ignored and does not return platform_current."""
        result = ProductLocator.locate(
            query="test",
            platform_goods_id="   ",
        )
        assert result.goods_id is None
        assert result.source == ProductLocator.SOURCE_NONE

    def test_whitespace_locked_goods_id_ignored(self):
        """Whitespace locked_goods_id is ignored and does not return session_locked."""
        result = ProductLocator.locate(
            query="test",
            locked_goods_id="   ",
        )
        assert result.goods_id is None
        assert result.source == ProductLocator.SOURCE_NONE

    def test_platform_goods_id_with_spaces_returns_stripped(self):
        """platform_goods_id with spaces returns stripped goods_id."""
        result = ProductLocator.locate(
            query="test",
            platform_goods_id="  123456  ",
        )
        assert result.goods_id == "123456"
        assert result.source == ProductLocator.SOURCE_PLATFORM

    def test_multiple_no_match_candidates_returns_none(self):
        """Multiple candidates with no matching terms returns none with reason not ambiguous_keyword_match."""
        result = ProductLocator.locate(
            query="hello world",
            candidates=[
                ProductCandidate(
                    goods_id="111111",
                    goods_name="iPhone 15",
                    search_terms=["iPhone"],
                ),
                ProductCandidate(
                    goods_id="222222",
                    goods_name="Samsung Galaxy",
                    search_terms=["Samsung"],
                ),
            ],
        )
        assert result.goods_id is None
        assert result.source == ProductLocator.SOURCE_NONE
        assert result.reason == "No product match found"

    def test_ambiguous_keyword_tie_returns_none(self):
        """Ambiguous keyword tie still returns None and reason ambiguous_keyword_match."""
        result = ProductLocator.locate(
            query="iPhone",
            candidates=[
                ProductCandidate(
                    goods_id="111111",
                    goods_name="iPhone 15",
                    search_terms=["iPhone"],
                ),
                ProductCandidate(
                    goods_id="222222",
                    goods_name="iPhone 14",
                    search_terms=["iPhone"],
                ),
            ],
        )
        assert result.goods_id is None
        assert result.source == ProductLocator.SOURCE_NONE
        assert result.reason == "ambiguous_keyword_match"


class TestProductCandidateDataclass:
    """Test ProductCandidate dataclass."""

    def test_product_candidate_creation(self):
        """ProductCandidate can be created with required fields."""
        candidate = ProductCandidate(
            goods_id="123456",
            goods_name="iPhone 15",
            search_terms=["iPhone", "15"],
        )
        assert candidate.goods_id == "123456"
        assert candidate.goods_name == "iPhone 15"
        assert candidate.search_terms == ["iPhone", "15"]

    def test_product_candidate_default_search_terms(self):
        """ProductCandidate defaults search_terms to empty list."""
        candidate = ProductCandidate(goods_id="123456", goods_name="iPhone 15")
        assert candidate.search_terms == []


class TestProductLocatorResultDataclass:
    """Test ProductLocatorResult dataclass."""

    def test_result_creation(self):
        """ProductLocatorResult can be created with all fields."""
        result = ProductLocatorResult(
            goods_id="123456",
            confidence=0.85,
            source="keyword",
            reason="Keyword match",
        )
        assert result.goods_id == "123456"
        assert result.confidence == 0.85
        assert result.source == "keyword"
        assert result.reason == "Keyword match"
