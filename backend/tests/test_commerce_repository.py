import uuid

from app.commerce.repository import _build_match_stmt

# Offline, no-DB statement-compilation tests -- same approach
# tests/test_knowledge_repository.py already takes for
# _build_search_stmt, since this repo has no existing precedent for a
# real-DB repository test.


def _compiled_sql(stmt) -> str:  # type: ignore[no-untyped-def]
    return str(stmt.compile(compile_kwargs={"literal_binds": False}))


class TestBuildMatchStmt:
    def test_tenant_id_is_always_in_the_where_clause(self) -> None:
        tenant_id = uuid.uuid4()
        sql = _compiled_sql(_build_match_stmt(tenant_id, "Widget", None))
        assert "fake_commerce_products.tenant_id" in sql

    def test_name_match_is_case_insensitive(self) -> None:
        sql = _compiled_sql(_build_match_stmt(uuid.uuid4(), "Widget", None))
        assert "lower(fake_commerce_products.name)" in sql

    def test_no_size_has_no_size_filter(self) -> None:
        sql = _compiled_sql(_build_match_stmt(uuid.uuid4(), "Widget", None))
        assert "size" not in sql.split("WHERE", 1)[1].split("ORDER BY", 1)[0]

    def test_size_given_adds_a_case_insensitive_size_filter(self) -> None:
        sql = _compiled_sql(_build_match_stmt(uuid.uuid4(), "Widget", "M"))
        where_clause = sql.split("WHERE", 1)[1].split("ORDER BY", 1)[0]
        assert "lower(fake_commerce_products.size)" in where_clause

    def test_orders_by_size_for_determinism(self) -> None:
        sql = _compiled_sql(_build_match_stmt(uuid.uuid4(), "Widget", None))
        assert "ORDER BY fake_commerce_products.size" in sql
