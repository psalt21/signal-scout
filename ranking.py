"""Signal Scout – scoring / ranking logic.

final_score = relevance_score + sum(tag_weights) + source_weight
"""

import json


def recalculate_scores(db):
    """Recompute final_score for every summarized item."""
    items = db.get_all_summarized_items()
    for item in items:
        tags = json.loads(item.get("tags", "[]"))
        tag_bonus = sum(db.get_tag_weight(t) for t in tags)
        source_bonus = db.get_source_weight(item.get("source", ""))
        relevance = item.get("relevance_score", 50)
        final = relevance + tag_bonus + source_bonus
        db.update_final_score(item["id"], final)
