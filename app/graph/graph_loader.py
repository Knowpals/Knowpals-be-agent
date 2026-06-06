from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple


_CONTRADICT_PREFIXES = re.compile(r"[非不无]")


class KnowledgeGraph:
    """In-memory knowledge graph loaded from graph_data.json.

    Provides node lookup (by label, alias, text) and BFS-based subgraph extraction
    so the agent can pull a small relevant subgraph around matched video concepts.
    """

    def __init__(self, graph_path: str = "app/graph_data.json"):
        self.graph_path = graph_path
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.edges: List[Dict[str, Any]] = []
        self.aliases: Dict[str, str] = {}
        self.diagnosis_rules: List[Dict[str, Any]] = []

        self._out_edges: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        self._in_edges: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        self._label_index: Dict[str, str] = {}
        self._alias_index: Dict[str, str] = {}

    def load(self, path: str | None = None) -> None:
        path = path or self.graph_path
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for n in data.get("nodes", []):
            nid = n["node_id"]
            self.nodes[nid] = n
            self._label_index[n["label"].lower().strip()] = nid

        for e in data.get("edges", []):
            self.edges.append(e)
            self._out_edges[e["from"]].append((e["relation"], e["to"]))
            self._in_edges[e["to"]].append((e["relation"], e["from"]))

        for a in data.get("aliases", []):
            self.aliases[a["alias"].lower().strip()] = a["node_id"]
            self._alias_index[a["alias"].lower().strip()] = a["node_id"]

        self.diagnosis_rules = data.get("diagnosis_rules", [])

    # ── node lookup ──────────────────────────────────────────────

    def find_by_label(self, label: str) -> Optional[str]:
        return self._label_index.get(label.lower().strip())

    def find_by_alias(self, alias: str) -> Optional[str]:
        return self._alias_index.get(alias.lower().strip())

    def search_by_text(self, query: str) -> List[Tuple[str, float]]:
        """Score nodes whose label relates to *query*.

        Strategies, tried in order:
          1. label == query                  (exact)
          2. query in label                  (query is substring)
          3. label in query                  (label is substring)
          4. query in desc                   (query in description)
          5. longest common substring ≥ 2    (shared keywords, with penalty for
             contradictory prefixes like 非/不/无 absent from query)
        """
        q = query.lower().strip()
        if not q:
            return []

        hits: list[tuple[str, float]] = []
        for nid, n in self.nodes.items():
            label = n.get("label", "").lower()
            desc = n.get("description", "").lower()

            score = self._match_score(q, label, desc)
            if score > 0:
                hits.append((nid, score))

        hits.sort(key=lambda x: -x[1])
        return hits

    @staticmethod
    def _match_score(q: str, label: str, desc: str) -> float:
        if q == label:
            return 1.0
        if q in label:
            return 0.8
        if label in q:
            return 0.75
        if q in desc:
            return 0.5

        # LCS-based
        lcs_len = _longest_common_substring(q, label)
        min_len = len(q)
        if lcs_len >= 2 and lcs_len / min_len >= 0.35:
            score = 0.35 + 0.35 * (lcs_len / min_len)
            # Penalize when label has a contradiction prefix absent from query
            if _has_contradiction(label, q):
                score *= 0.4
            return score

        return 0.0

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        return self.nodes.get(node_id)

    # ── graph traversal ──────────────────────────────────────────

    def get_neighbors(
        self, node_id: str, max_hops: int = 1, relation: str | None = None
    ) -> Set[str]:
        """BFS from *node_id* up to *max_hops* hops.

        If *relation* is set, only traverse edges of that relation type.
        """
        visited: set[str] = {node_id}
        frontier: set[str] = {node_id}

        for _ in range(max_hops):
            if not frontier:
                break
            nxt: set[str] = set()
            for nid in frontier:
                for rel, neighbor in self._out_edges.get(nid, []):
                    if relation is not None and rel != relation:
                        continue
                    if neighbor not in visited:
                        visited.add(neighbor)
                        nxt.add(neighbor)
                for rel, neighbor in self._in_edges.get(nid, []):
                    if relation is not None and rel != relation:
                        continue
                    if neighbor not in visited:
                        visited.add(neighbor)
                        nxt.add(neighbor)
            frontier = nxt

        return visited

    # ── subgraph extraction ──────────────────────────────────────

    def extract_subgraph(
        self,
        seed_ids: List[str],
        max_hops: int = 2,
        node_types: Set[str] | None = None,
        relations: Set[str] | None = None,
    ) -> Dict[str, Any]:
        """Extract the subgraph around *seed_ids* (BFS, *max_hops* deep).

        Returns a serialisable dict usable as LLM context.
        """
        all_ids: set[str] = set()
        for sid in seed_ids:
            if sid in self.nodes:
                all_ids.add(sid)
                all_ids |= self.get_neighbors(sid, max_hops=max_hops)

        if node_types:
            all_ids = {
                nid
                for nid in all_ids
                if self.nodes.get(nid, {}).get("type") in node_types
            }

        sub_nodes = []
        for nid in sorted(all_ids):
            n = self.nodes[nid]
            sub_nodes.append(
                {
                    "node_id": nid,
                    "label": n["label"],
                    "type": n["type"],
                    "description": n.get("description", ""),
                    "domain": n.get("domain", ""),
                    "level": n.get("level", ""),
                }
            )

        sub_edges = []
        for e in self.edges:
            if e["from"] in all_ids and e["to"] in all_ids:
                if relations and e["relation"] not in relations:
                    continue
                sub_edges.append(
                    {
                        "edge_id": e["edge_id"],
                        "from": e["from"],
                        "to": e["to"],
                        "relation": e["relation"],
                    }
                )

        return {
            "nodes": sub_nodes,
            "edges": sub_edges,
            "metadata": {
                "node_count": len(sub_nodes),
                "edge_count": len(sub_edges),
                "seed_ids": seed_ids,
            },
        }


# ── helpers ──────────────────────────────────────────────────────


def _longest_common_substring(a: str, b: str) -> int:
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    best = 0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
                if dp[i][j] > best:
                    best = dp[i][j]
    return best


def _has_contradiction(label: str, query: str) -> bool:
    """Return True if *label* contains 非/不/无 absent from *query*."""
    for m in _CONTRADICT_PREFIXES.finditer(label):
        ch = m.group()
        # Check that this character starts a real negation word in label
        pos = m.start()
        if ch not in query:
            return True
    return False
