"""
Recommendation Worker — Stage 6.

DSA Focus:
----------
- Graphs: user-item interactions as an adjacency list
- Collaborative Filtering: find similar users, recommend their items
- Heaps: efficiently get Top-K recommendations
- Hash Maps: fast lookups for user history and item scores

Python Internals Focus:
-----------------------
- defaultdict for graph construction
- heapq.nlargest for Top-K (O(n log k) — better than sorting when k << n)
- set operations for filtering already-seen items
"""
import heapq
from collections import defaultdict
from typing import Any

from app.workers.base import BaseJobHandler


class RecommendationHandler(BaseJobHandler[dict[str, Any], dict[str, Any]]):
    """
    Graph-based collaborative filtering recommendation engine.

    Architecture:
    - Build a bipartite graph: users ↔ items
    - Find similar users (shared items)
    - Score unseen items based on similar users' preferences
    - Return Top-K using a heap
    """

    def validate_input(self, input_payload: dict[str, Any]) -> None:
        user_id = input_payload.get("user_id")
        interactions = input_payload.get("interactions")

        if user_id is None:
            raise ValueError("Recommendations require a 'user_id'")

        if interactions is None:
            raise ValueError(
                "Recommendations require 'interactions': a list of "
                "{'user_id': str, 'item_id': str, 'rating': float} objects"
            )

        if not isinstance(interactions, list) or len(interactions) == 0:
            raise ValueError("'interactions' must be a non-empty list")

        for entry in interactions:
            if not isinstance(entry, dict):
                raise ValueError("Each interaction must be a dict")
            if "user_id" not in entry or "item_id" not in entry:
                raise ValueError(
                    "Each interaction must have 'user_id' and 'item_id'"
                )

    def process(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """
        DSA: Graph-based Collaborative Filtering.

        Steps:
        1. Build bipartite graph (users → items, items → users)  — O(E)
        2. Find target user's items — O(1) hash map lookup
        3. Find similar users (share items with target) — O(degree * degree)
        4. Score candidate items from similar users — O(similar_users * their_items)
        5. Get Top-K using heap — O(n log k)

        Where E = total interactions, k = number of recommendations desired.
        """
        user_id = input_payload["user_id"]
        interactions = input_payload["interactions"]
        top_k = input_payload.get("top_k", 10)

        user_to_items, item_to_users, user_ratings = self._build_graph(
            interactions
        )

        if user_id not in user_to_items:
            return {
                "recommendations": [],
                "reason": "user has no interaction history",
            }

        user_items = user_to_items[user_id]

        similar_users = self._find_similar_users(
            user_id, user_items, item_to_users
        )

        scored_items = self._score_candidates(
            user_items, similar_users, user_to_items, user_ratings
        )

        top_recommendations = self._top_k_by_heap(scored_items, k=top_k)

        return {
            "recommendations": top_recommendations,
            "user_id": user_id,
            "user_item_count": len(user_items),
            "similar_users_found": len(similar_users),
        }

    def format_result(self, raw_result: dict[str, Any]) -> dict[str, Any]:
        return raw_result

    def _build_graph(
        self, interactions: list[dict[str, Any]]
    ) -> tuple[
        dict[str, set[str]],
        dict[str, set[str]],
        dict[str, dict[str, float]],
    ]:
        """
        DSA: Build adjacency list representation of bipartite graph.

        Graph structure:
        - user_to_items: {user_id: {item_a, item_b, ...}}  (adjacency list)
        - item_to_users: {item_id: {user_x, user_y, ...}}  (reverse index)
        - user_ratings:  {user_id: {item_id: rating}}       (edge weights)

        Time: O(E) where E = number of interactions
        Space: O(E) for the adjacency lists

        Using defaultdict: Python creates the default value (set/dict)
        automatically on first access — no KeyError checks needed.
        """
        user_to_items: dict[str, set[str]] = defaultdict(set)
        item_to_users: dict[str, set[str]] = defaultdict(set)
        user_ratings: dict[str, dict[str, float]] = defaultdict(dict)

        for interaction in interactions:
            uid = str(interaction["user_id"])
            iid = str(interaction["item_id"])
            rating = float(interaction.get("rating", 1.0))

            user_to_items[uid].add(iid)
            item_to_users[iid].add(uid)
            user_ratings[uid][iid] = rating

        return user_to_items, item_to_users, user_ratings

    def _find_similar_users(
        self,
        target_user: str,
        target_items: set[str],
        item_to_users: dict[str, set[str]],
    ) -> dict[str, float]:
        """
        DSA: Find similar users via shared items (Jaccard-like scoring).

        For each item the target user interacted with:
          - Look up all other users who interacted with that item
          - Each shared item increases that user's similarity score

        Final similarity = shared_items / union_of_items (Jaccard index)

        Time: O(|target_items| * avg_users_per_item)
        """
        similarity_scores: dict[str, int] = defaultdict(int)

        for item in target_items:
            for other_user in item_to_users.get(item, set()):
                if other_user != target_user:
                    similarity_scores[other_user] += 1

        similarities: dict[str, float] = {}
        for other_user, shared_count in similarity_scores.items():
            union_size = len(target_items | item_to_users.get(other_user, set()))
            if union_size > 0:
                similarities[other_user] = shared_count / union_size

        return similarities

    def _score_candidates(
        self,
        user_items: set[str],
        similar_users: dict[str, float],
        user_to_items: dict[str, set[str]],
        user_ratings: dict[str, dict[str, float]],
    ) -> dict[str, float]:
        """
        DSA: Weighted scoring of candidate items.

        For each similar user:
          - Look at items they liked that target user hasn't seen
          - Score = similarity_weight * their_rating

        Accumulate scores in a hash map: O(1) per update.

        This is the core of collaborative filtering:
        "Users similar to you liked X, so you might like X too."
        """
        item_scores: dict[str, float] = defaultdict(float)

        for other_user, similarity in similar_users.items():
            other_items = user_to_items.get(other_user, set())
            unseen_items = other_items - user_items

            for item in unseen_items:
                rating = user_ratings[other_user].get(item, 1.0)
                item_scores[item] += similarity * rating

        return dict(item_scores)

    @staticmethod
    def _top_k_by_heap(
        scored_items: dict[str, float], k: int
    ) -> list[dict[str, Any]]:
        """
        DSA: Top-K elements using a heap.

        heapq.nlargest uses a min-heap of size k internally:
        - Push first k elements onto heap
        - For each remaining element: if larger than heap min, replace
        - Result: k largest elements

        Time: O(n log k) — better than O(n log n) full sort when k << n
        Space: O(k) for the heap

        Example: 1 million items, top 10 → O(n log 10) vs O(n log n)
        That's roughly 3x fewer comparisons.
        """
        if not scored_items:
            return []

        top_items = heapq.nlargest(k, scored_items.items(), key=lambda x: x[1])

        return [
            {"item_id": item_id, "score": round(score, 4)}
            for item_id, score in top_items
        ]