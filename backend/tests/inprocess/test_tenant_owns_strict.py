"""Both ownership APIs fail closed for reads and mutations."""
from middleware.actor_context import tenant_owns, tenant_owns_strict


def test_strict_allows_an_exact_match():
    assert tenant_owns_strict("biz-a", "biz-a") is True


def test_strict_refuses_a_disagreeing_match():
    assert tenant_owns_strict("biz-a", "biz-b") is False


def test_strict_refuses_when_the_document_has_no_businessId():
    """The core behavioral difference from tenant_owns(): a document with
    no businessId at all must be refused for a mutation, not allowed."""
    assert tenant_owns_strict(None, "biz-a") is False
    assert tenant_owns(None, "biz-a") is False


def test_strict_refuses_when_the_caller_businessId_is_unknown():
    assert tenant_owns_strict("biz-a", None) is False
    assert tenant_owns("biz-a", None) is False


def test_strict_refuses_when_both_sides_are_missing():
    assert tenant_owns_strict(None, None) is False
    assert tenant_owns(None, None) is False
