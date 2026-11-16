"""Merkle tree over the audit ledger (RFC 6962 style, SHA-256).

Leaf hash = H(0x00 + data); inner hash = H(0x01 + left + right). The two prefixes stop an
inner node from being passed off as a leaf (second-preimage attack). n leaves are split at
k = the largest power of two below n. An inclusion proof holds about log2(n) hashes, so one
entry can be checked against a published root without reading the whole ledger.
"""
import hashlib


def _h(b):
    return hashlib.sha256(b).digest()


def leaf_hash(data):
    return _h(b"\x00" + data)


def node_hash(left, right):
    return _h(b"\x01" + left + right)


def _split(n):
    """Largest power of two strictly below n (needs n >= 2)."""
    k = 1
    while k * 2 < n:
        k *= 2
    return k


def root(leaves):
    """Root of a list of leaf hashes (each made with leaf_hash). Empty tree = H(b"")."""
    n = len(leaves)
    if n == 0:
        return _h(b"")
    if n == 1:
        return leaves[0]
    k = _split(n)
    return node_hash(root(leaves[:k]), root(leaves[k:]))


def prove(leaves, index):
    """Inclusion proof for leaves[index]: sibling hashes from the bottom up."""
    n = len(leaves)
    if not 0 <= index < n:
        raise IndexError("leaf index out of range")
    if n == 1:
        return []
    k = _split(n)
    if index < k:
        return prove(leaves[:k], index) + [root(leaves[k:])]
    return prove(leaves[k:], index - k) + [root(leaves[:k])]


def _rebuild(leaf, index, size, proof):
    """Recompute the root from a proof (top-level sibling is last), or None if malformed."""
    if size == 1:
        return leaf if not proof else None
    if not proof:
        return None
    k = _split(size)
    sib, rest = proof[-1], proof[:-1]
    if index < k:
        sub = _rebuild(leaf, index, k, rest)
        return None if sub is None else node_hash(sub, sib)
    sub = _rebuild(leaf, index - k, size - k, rest)
    return None if sub is None else node_hash(sib, sub)


def verify(leaf, index, size, proof, expected_root):
    """True if `leaf` sits at `index` in a tree of `size` leaves whose root is expected_root."""
    if not 0 <= index < size:
        return False
    got = _rebuild(leaf, index, size, list(proof))
    return got is not None and got == expected_root
