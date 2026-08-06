"""Recommendation worker using collaborative filtering over user-item interactions."""
import heapq
from collections import defaultdict
from typing import Any

from app.workers.base import BaseJobHandler


class RecommendationHandler(BaseJobHandler[dict[str, Any], dict[str, Any]]):
    """Collaborative filtering: similar users → scored unseen items → top-K."""

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
        """Build interaction graph, find similar users, score candidates, return top-K."""
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
        """Build user→items, item→users, and rating maps from interactions."""
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
        """Score other users by Jaccard overlap on shared items."""
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
        """Score unseen items from similar users weighted by similarity and rating."""
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
        """Return the top-k scored items."""
        if not scored_items:
            return []

        top_items = heapq.nlargest(k, scored_items.items(), key=lambda x: x[1])

        return [
            {"item_id": item_id, "score": round(score, 4)}
            for item_id, score in top_items
        ]
