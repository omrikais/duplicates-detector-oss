"""TF-IDF cosine similarity for document deduplication.

Opt-in content method (--content-method tfidf). Pairwise comparison,
not cached — serial scoring path like SSIM.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from duplicates_detector.metadata import VideoMetadata


def build_tfidf_matrix(items: list[VideoMetadata]) -> Any:
    """Build a TF-IDF sparse matrix from document text content.

    Items with None text_content are treated as empty strings.
    Returns a scipy sparse matrix with one row per item.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer

    texts = [item.text_content or "" for item in items]
    vectorizer = TfidfVectorizer()
    try:
        return vectorizer.fit_transform(texts)
    except ValueError:
        # Empty vocabulary — all documents blank or only single-char tokens.
        return None


def compare_tfidf(matrix: Any, i: int, j: int) -> float:
    """Compute cosine similarity between two rows in a TF-IDF matrix.

    Returns similarity in [0.0, 1.0].
    """
    from sklearn.metrics.pairwise import cosine_similarity

    sim = cosine_similarity(matrix[i : i + 1], matrix[j : j + 1])
    return float(sim[0, 0])
