import hashlib
import pytest
from app import merkle as m


def _leaves(n):
    return [m.leaf_hash(f"entry-{i}".encode()) for i in range(n)]


def _root_bottom_up(leaves):
    """Independent implementation: pair neighbours, carry an odd last node up unchanged."""
    level = list(leaves)
    while len(level) > 1:
        nxt = [m.node_hash(level[i], level[i + 1]) for i in range(0, len(level) - 1, 2)]
        if len(level) % 2:
            nxt.append(level[-1])
        level = nxt
    return level[0]


def test_root_matches_independent_implementation():
    for n in range(1, 130):
        L = _leaves(n)
        assert m.root(L) == _root_bottom_up(L), n


def test_every_leaf_proves_and_proof_is_short():
    for n in list(range(1, 70)) + [100, 128, 129]:
        L = _leaves(n)
        r = m.root(L)
        for i in range(n):
            p = m.prove(L, i)
            assert m.verify(L[i], i, n, p, r), (n, i)
            assert len(p) <= (n - 1).bit_length(), (n, i)   # at most ceil(log2 n) hashes


def test_tampering_is_detected():
    n = 37
    L = _leaves(n)
    r = m.root(L)
    wrong_root = hashlib.sha256(r).digest()
    for i in range(n):
        p = m.prove(L, i)
        assert not m.verify(m.leaf_hash(b"forged"), i, n, p, r)        # wrong data
        assert not m.verify(L[i], (i + 1) % n, n, p, r)                 # wrong position
        assert not m.verify(L[i], i, n, p, wrong_root)                  # wrong root
        assert not m.verify(L[i], i, n, p[:-1], r)                      # proof too short
        assert not m.verify(L[i], i, n, p + [r], r)                     # proof too long
        for j in range(len(p)):                                         # any flipped sibling
            q = list(p)
            q[j] = hashlib.sha256(q[j]).digest()
            assert not m.verify(L[i], i, n, q, r)


def test_root_changes_if_any_leaf_changes_or_one_is_appended():
    L = _leaves(20)
    r = m.root(L)
    for i in range(20):
        M = list(L)
        M[i] = m.leaf_hash(b"changed")
        assert m.root(M) != r
    assert m.root(L + [m.leaf_hash(b"new")]) != r


def test_leaf_and_inner_hashes_use_different_prefixes():
    a, b = m.leaf_hash(b"a"), m.leaf_hash(b"b")
    assert m.node_hash(a, b) != m.leaf_hash(a + b)


def test_edge_cases():
    assert m.root([]) == hashlib.sha256(b"").digest()
    L = _leaves(1)
    assert m.root(L) == L[0]
    assert m.prove(L, 0) == []
    assert m.verify(L[0], 0, 1, [], L[0])
    assert not m.verify(L[0], 0, 1, [L[0]], L[0])
    assert not m.verify(L[0], 1, 1, [], L[0])
    assert not m.verify(L[0], 0, 0, [], L[0])
    with pytest.raises(IndexError):
        m.prove(L, 1)
