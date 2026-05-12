"""Product locator primitive for V3 prompt-first architecture.

Deterministic goods_id resolution before PromptBuilder execution.
No external dependencies - pure dataclasses and regex only.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import unquote


@dataclass
class ProductCandidate:
    """Candidate product from catalog."""

    goods_id: str
    goods_name: str
    search_terms: List[str] = field(default_factory=list)


@dataclass
class ProductLocatorResult:
    """Result of product location attempt.

    Attributes:
        goods_id: Resolved goods_id or None if none.
        confidence: Source confidence (1.0=platform, 0.95=locked, 0.9=parsed, 0.60-0.85=keyword, 0.0=none).
        source: Where goods_id came from (platform_current, session_locked, link, keyword, none).
        reason: Human-readable explanation.
    """

    goods_id: str | None
    confidence: float
    source: str
    reason: str


class ProductLocator:
    """Deterministic product locator for prompt-first architecture.

    Priority order (strict):
    1. platform_goods_id -> confidence 1.0
    2. locked_goods_id -> confidence 0.95
    3. parsed link/text goods_id -> confidence 0.9
    4. keyword fallback -> confidence 0.60 to 0.85
    5. none -> confidence 0.0

    Keyword scoring:
    - Normalize query, goods_name, search_terms (lowercase ASCII, remove whitespace/punctuation, preserve Chinese)
    - Full goods_name in query: 0.85
    - Query in goods_name: 0.75
    - Each matched search_term adds 0.12 starting from 0.60, capped at 0.84
    - Final score = max(name score, term score)
    - Tied top scores -> none with reason "ambiguous_keyword_match"
    """

    SOURCE_PLATFORM = "platform_current"
    SOURCE_LOCKED = "session_locked"
    SOURCE_LINK = "link"
    SOURCE_KEYWORD = "keyword"
    SOURCE_NONE = "none"

    CONFIDENCE_PLATFORM = 1.0
    CONFIDENCE_LOCKED = 0.95
    CONFIDENCE_LINK = 0.9
    CONFIDENCE_KEYWORD_MIN = 0.60
    CONFIDENCE_KEYWORD_MAX = 0.85
    CONFIDENCE_NONE = 0.0

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize text for keyword matching.

        - Lowercase ASCII
        - Remove whitespace and punctuation/separators
        - Preserve Chinese characters, ASCII letters, and digits
        """
        return re.sub(r"[^一-鿿a-z0-9]", "", text.lower())

    @staticmethod
    def _extract_goods_id_from_text(text: str) -> Optional[str]:
        """Extract goods_id from link or text.

        Patterns:
        - goods_id=123456
        - goodsId=123456
        - goods_id%3D123456 (URL-encoded)
        - 商品ID:123456
        - 商品id123456

        Returns None if not found or invalid (must be 6-20 digits).
        """
        if not text:
            return None

        # URL decode
        decoded = unquote(text)

        # Pattern 1: goods_id= or goodsId= with digits (word boundary to reject >20 digits)
        match = re.search(r"goods_?[iI]d=(\d{6,20})(?!\d)", decoded)
        if match:
            return match.group(1)

        # Pattern 2: Chinese patterns 商品ID: or 商品id with word boundary
        match = re.search(r"商品[iI][dD]:?\s*(\d{6,20})(?!\d)", decoded)
        if match:
            return match.group(1)

        # Pattern 3: Chinese pattern without colon 商品id123456
        match = re.search(r"商品[iI][dD](\d{6,20})(?!\d)", decoded)
        if match:
            return match.group(1)

        return None

    @staticmethod
    def _score_keyword_match(query: str, candidate: ProductCandidate) -> float:
        """Score a keyword match.

        - Normalize query, goods_name, search_terms
        - Full goods_name in query: 0.85
        - Query in goods_name: 0.75
        - Each matched search_term adds 0.12 starting from 0.60, capped at 0.84
        - Final score = max(name score, term score)
        - No match: 0.0
        """
        norm_query = ProductLocator._normalize(query)
        norm_name = ProductLocator._normalize(candidate.goods_name)

        # Name containment scores
        name_score = 0.0

        if norm_name and norm_name in norm_query:
            name_score = 0.85
        elif norm_query and norm_query in norm_name:
            name_score = 0.75

        # Term matching score
        term_score = 0.0
        matched_terms = 0

        for term in candidate.search_terms:
            norm_term = ProductLocator._normalize(term)
            if norm_term and norm_term in norm_query:
                matched_terms += 1

        if matched_terms > 0:
            term_score = ProductLocator.CONFIDENCE_KEYWORD_MIN + matched_terms * 0.12
            term_score = min(term_score, 0.84)

        return max(name_score, term_score)

    @classmethod
    def locate(
        cls,
        query: str,
        *,
        platform_goods_id: str | None = None,
        locked_goods_id: str | None = None,
        candidates: list[ProductCandidate] | None = None,
    ) -> ProductLocatorResult:
        """Locate product with strict priority ordering.

        Args:
            query: User query text.
            platform_goods_id: Current platform context goods_id (highest priority).
            locked_goods_id: Session-locked goods_id.
            candidates: Product catalog candidates for keyword fallback.

        Returns:
            ProductLocatorResult with goods_id, confidence, source, and reason.
        """
        # Initialize candidates to empty list if None
        if candidates is None:
            candidates = []

        # Priority 1: platform_goods_id (non-empty after strip)
        if platform_goods_id:
            stripped_platform = platform_goods_id.strip()
            if stripped_platform:
                return ProductLocatorResult(
                    goods_id=stripped_platform,
                    confidence=cls.CONFIDENCE_PLATFORM,
                    source=cls.SOURCE_PLATFORM,
                    reason=f"Platform context goods_id={stripped_platform}",
                )

        # Priority 2: locked_goods_id (non-empty after strip)
        if locked_goods_id:
            stripped_locked = locked_goods_id.strip()
            if stripped_locked:
                return ProductLocatorResult(
                    goods_id=stripped_locked,
                    confidence=cls.CONFIDENCE_LOCKED,
                    source=cls.SOURCE_LOCKED,
                    reason=f"Session locked goods_id={stripped_locked}",
                )

        # Priority 3: parsed link/text goods_id
        parsed_id = cls._extract_goods_id_from_text(query)
        if parsed_id:
            return ProductLocatorResult(
                goods_id=parsed_id,
                confidence=cls.CONFIDENCE_LINK,
                source=cls.SOURCE_LINK,
                reason=f"Parsed goods_id={parsed_id} from query",
            )

        # Priority 4: keyword fallback
        if candidates:
            scores = []
            for candidate in candidates:
                score = cls._score_keyword_match(query, candidate)
                scores.append((score, candidate))

            if scores:
                # Sort by score descending
                scores.sort(key=lambda x: x[0], reverse=True)
                top_score, top_candidate = scores[0]

                # Check for ambiguity (only if top score > 0.0)
                if top_score > 0.0 and len(scores) > 1 and scores[1][0] == top_score:
                    return ProductLocatorResult(
                        goods_id=None,
                        confidence=cls.CONFIDENCE_NONE,
                        source=cls.SOURCE_NONE,
                        reason="ambiguous_keyword_match",
                    )

                if top_score > 0.0:
                    return ProductLocatorResult(
                        goods_id=top_candidate.goods_id,
                        confidence=top_score,
                        source=cls.SOURCE_KEYWORD,
                        reason=f"Keyword match goods_id={top_candidate.goods_id} score={top_score:.2f}",
                    )

        # Priority 5: none
        return ProductLocatorResult(
            goods_id=None,
            confidence=cls.CONFIDENCE_NONE,
            source=cls.SOURCE_NONE,
            reason="No product match found",
        )
