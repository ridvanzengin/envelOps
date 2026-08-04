import uuid
from unittest.mock import AsyncMock

from app.commerce.models import FakeCommerceProduct
from app.commerce.repository import (
    FakeCommerceProductRepository,
    _is_match,
    _significant_words,
)


def _row(name: str, size: str | None, in_stock: bool = True) -> FakeCommerceProduct:
    return FakeCommerceProduct(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name=name,
        size=size,
        in_stock=in_stock,
        quantity_available=5 if in_stock else None,
        restock_eta_days=None if in_stock else 10,
    )


class TestSignificantWords:
    def test_lowercases_and_splits_on_whitespace(self) -> None:
        assert _significant_words("Oversized Hoodie") == frozenset({"oversized", "hoodie"})

    def test_strips_a_trailing_s_per_word(self) -> None:
        assert _significant_words("Bucket Hats") == frozenset({"bucket", "hat"})

    def test_does_not_strip_a_lone_s(self) -> None:
        # len(word) > 1 guard -- a single "s" token stripped to "" would
        # be a vacuous word that could match anything.
        assert "" not in _significant_words("s")

    def test_ignores_punctuation(self) -> None:
        assert _significant_words("do you sell hats?") == frozenset(
            {"do", "you", "sell", "hat"}
        )

    def test_empty_string_has_no_words(self) -> None:
        assert _significant_words("???") == frozenset()


class TestIsMatch:
    def test_query_missing_a_descriptive_word_still_matches(self) -> None:
        # The actual regression case (found live 2026-08-04): "hoodies"
        # alone didn't match "Oversized Hoodie" under exact/plural-only
        # matching -- customers don't say the full catalog name.
        query = _significant_words("hoodies")
        catalog = _significant_words("Oversized Hoodie")
        assert _is_match(query, catalog) is True

    def test_fuller_customer_phrase_matches_the_reverse_way(self) -> None:
        query = _significant_words("do you sell the oversized hoodie")
        catalog = _significant_words("Oversized Hoodie")
        assert _is_match(query, catalog) is True

    def test_off_catalog_query_does_not_match_by_partial_overlap(self) -> None:
        # The actual bounded-catalog safety property (docs/plans/
        # fake-commerce-platform-integration.md): an off-catalog query
        # must never coincidentally match a real product just by sharing
        # a word or substring.
        query = _significant_words("ak47")
        catalog = _significant_words("Oversized Hoodie")
        assert _is_match(query, catalog) is False

    def test_disjoint_multi_word_query_does_not_match(self) -> None:
        query = _significant_words("red hoodie")
        catalog = _significant_words("Oversized Hoodie")
        assert _is_match(query, catalog) is False

    def test_empty_query_never_matches(self) -> None:
        assert _is_match(frozenset(), _significant_words("Oversized Hoodie")) is False


class TestFindMatching:
    async def test_matches_a_word_containment_hit(self) -> None:
        session = AsyncMock()
        session.scalars = AsyncMock(return_value=[_row("Oversized Hoodie", "M")])
        repo = FakeCommerceProductRepository(session)
        result = await repo.find_matching(uuid.uuid4(), "hoodies", None)
        assert result is not None
        assert result.name == "Oversized Hoodie"

    async def test_filters_by_size_when_given(self) -> None:
        session = AsyncMock()
        session.scalars = AsyncMock(
            return_value=[
                _row("Oversized Hoodie", "S"),
                _row("Oversized Hoodie", "M", in_stock=False),
            ]
        )
        repo = FakeCommerceProductRepository(session)
        result = await repo.find_matching(uuid.uuid4(), "hoodie", "M")
        assert result is not None
        assert result.size == "M"
        assert result.in_stock is False

    async def test_returns_none_when_size_does_not_match_any_row(self) -> None:
        session = AsyncMock()
        session.scalars = AsyncMock(return_value=[_row("Oversized Hoodie", "S")])
        repo = FakeCommerceProductRepository(session)
        result = await repo.find_matching(uuid.uuid4(), "hoodie", "XL")
        assert result is None

    async def test_returns_none_for_an_off_catalog_query(self) -> None:
        session = AsyncMock()
        session.scalars = AsyncMock(return_value=[_row("Oversized Hoodie", "M")])
        repo = FakeCommerceProductRepository(session)
        result = await repo.find_matching(uuid.uuid4(), "AK-47", None)
        assert result is None

    async def test_picks_deterministically_when_size_omitted(self) -> None:
        session = AsyncMock()
        session.scalars = AsyncMock(
            return_value=[_row("Oversized Hoodie", "S"), _row("Oversized Hoodie", "L")]
        )
        repo = FakeCommerceProductRepository(session)
        first = await repo.find_matching(uuid.uuid4(), "hoodie", None)
        session.scalars = AsyncMock(
            return_value=[_row("Oversized Hoodie", "L"), _row("Oversized Hoodie", "S")]
        )
        second = await repo.find_matching(uuid.uuid4(), "hoodie", None)
        assert first is not None
        assert second is not None
        assert first.size == second.size == "L"
