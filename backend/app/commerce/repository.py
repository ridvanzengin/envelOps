import re
import uuid

from app.commerce.models import FakeCommerceProduct
from app.core.repository import TenantScopedRepository

_WORD_RE = re.compile(r"[a-z0-9]+")


def _significant_words(text: str) -> frozenset[str]:
    """Lowercased, singular/plural-insensitive (a trailing "s" stripped
    per word) word set -- what _is_match compares on, not full-string
    equality. Split out for its own focused unit tests."""
    words = _WORD_RE.findall(text.lower())
    return frozenset(
        word[:-1] if word.endswith("s") and len(word) > 1 else word for word in words
    )


def _is_match(query_words: frozenset[str], catalog_words: frozenset[str]) -> bool:
    """True when one word set wholly contains the other -- "hoodies"
    ({hoodie}) matches "Oversized Hoodie" ({oversized, hoodie}) since the
    query's words are a subset of the catalog name's; a fuller customer
    phrase matches the reverse way. Found live (2026-08-04): singular/
    plural-insensitive *exact*-name matching alone still missed this --
    "hoodie"/"hat"/"joggers" are missing a descriptive word a real
    multi-word catalog name has ("Oversized Hoodie", "Bucket Hat",
    "Cargo Joggers"), which is how people actually talk, not an edge
    case. Deliberately whole-word containment, not arbitrary substring
    matching (docs/plans/fake-commerce-platform-integration.md's bounded-
    catalog design): every word on the shorter side must be a real,
    whole word on the other side, so an off-catalog query ("ak47") can
    never coincidentally match a real product just by partial text
    overlap."""
    if not query_words or not catalog_words:
        return False
    return query_words <= catalog_words or catalog_words <= query_words


class FakeCommerceProductRepository(TenantScopedRepository[FakeCommerceProduct]):
    model = FakeCommerceProduct

    async def find_matching(
        self, tenant_id: uuid.UUID, name: str, size: str | None
    ) -> FakeCommerceProduct | None:
        """Word-containment match on name (see _is_match), exact
        case-insensitive match on size when given. Filters in Python, not
        SQL: this project's catalogs are small (a handful to a few dozen
        rows per tenant -- see the plan doc), and word-set containment
        doesn't map onto a simple SQL WHERE clause the way exact/IN
        matching did -- fetching the tenant's own rows (already
        tenant-scoped via list()) and matching in Python is far more
        readable than the Postgres array/full-text-search machinery the
        SQL equivalent would need, for no real cost at this scale. If
        size is omitted, any size row matches (ordered for determinism,
        not aggregated across variants -- see the plan doc's "lean flat"
        note)."""
        query_words = _significant_words(name)
        candidates = await self.list(tenant_id)
        if size is not None:
            normalized_size = size.strip().lower()
            candidates = [
                c for c in candidates if (c.size or "").strip().lower() == normalized_size
            ]
        matches = [c for c in candidates if _is_match(query_words, _significant_words(c.name))]
        matches.sort(key=lambda c: c.size or "")
        return matches[0] if matches else None
