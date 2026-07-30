import uuid

from app.knowledge.repository import _build_search_stmt

# Offline, no-DB statement-compilation tests -- this repo has no existing
# precedent for a real-DB repository test, so full live verification of
# pgvector's actual cosine-distance filtering happens manually (Test
# Console / scripts/run_synthetic_conversations.py), not here. This is
# the fast, no-infrastructure check that the SQL shape itself is right.


def _compiled_sql(stmt) -> str:  # type: ignore[no-untyped-def]
    return str(stmt.compile(compile_kwargs={"literal_binds": False}))


class TestBuildSearchStmt:
    def test_no_max_distance_has_no_distance_filter(self) -> None:
        # pgvector's cosine_distance operator itself compiles to "<=>",
        # which contains "<=" as a substring -- count occurrences of the
        # two separately rather than a naive "'<=' not in sql", or the
        # ORDER BY's own "<=>" would look like a stray filter.
        stmt = _build_search_stmt(uuid.uuid4(), [0.1, 0.2], limit=5, max_distance=None)
        sql = _compiled_sql(stmt)
        assert sql.count("<=") == sql.count("<=>")  # no standalone "<=" beyond the operator
        assert sql.count("<=>") == 1  # only the ORDER BY's distance expression
        assert "tenant_id" in sql
        assert "ORDER BY" in sql
        assert "LIMIT" in sql

    def test_max_distance_adds_a_where_clause_using_the_same_distance_expression(
        self,
    ) -> None:
        stmt = _build_search_stmt(uuid.uuid4(), [0.1, 0.2], limit=5, max_distance=0.5)
        sql = _compiled_sql(stmt)
        # A standalone "<=" (the threshold comparison) beyond the two
        # "<=>" distance-expression occurrences (WHERE + ORDER BY) --
        # the same expression used for filtering and ordering, not a
        # different one that could silently produce a mismatched result
        # set.
        assert sql.count("<=>") == 2
        assert sql.count("<=") > sql.count("<=>")

    def test_tenant_id_is_always_in_the_where_clause(self) -> None:
        tenant_id = uuid.uuid4()
        stmt = _build_search_stmt(tenant_id, [0.1], limit=5, max_distance=None)
        sql = _compiled_sql(stmt)
        assert "knowledge_chunks.tenant_id" in sql
