"""Tests for duplicates_detector.clip — CLIP preprocessing, comparison, and inference."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


class TestPreprocessImage:
    """Tests for _preprocess_image."""

    def test_output_shape_and_dtype(self) -> None:
        """Preprocessed output is (1, 3, 224, 224) float32."""
        from PIL import Image

        from duplicates_detector.clip import _preprocess_image

        img = Image.new("RGB", (640, 480), color=(128, 64, 32))
        result = _preprocess_image(img)
        assert result.shape == (1, 3, 224, 224)
        assert result.dtype == np.float32

    def test_square_image(self) -> None:
        """Square image is resized and cropped to 224x224."""
        from PIL import Image

        from duplicates_detector.clip import _preprocess_image

        img = Image.new("RGB", (300, 300), color=(100, 100, 100))
        result = _preprocess_image(img)
        assert result.shape == (1, 3, 224, 224)

    def test_tall_image(self) -> None:
        """Tall image (portrait) preprocesses correctly."""
        from PIL import Image

        from duplicates_detector.clip import _preprocess_image

        img = Image.new("RGB", (100, 500), color=(200, 100, 50))
        result = _preprocess_image(img)
        assert result.shape == (1, 3, 224, 224)

    def test_wide_image(self) -> None:
        """Wide image (landscape) preprocesses correctly."""
        from PIL import Image

        from duplicates_detector.clip import _preprocess_image

        img = Image.new("RGB", (500, 100), color=(50, 100, 200))
        result = _preprocess_image(img)
        assert result.shape == (1, 3, 224, 224)

    def test_grayscale_converted_to_rgb(self) -> None:
        """Grayscale image is converted to RGB before preprocessing."""
        from PIL import Image

        from duplicates_detector.clip import _preprocess_image

        img = Image.new("L", (300, 300), color=128)
        result = _preprocess_image(img)
        assert result.shape == (1, 3, 224, 224)

    def test_normalization_applied(self) -> None:
        """Output values are normalized (not in 0-255 range)."""
        from PIL import Image

        from duplicates_detector.clip import _preprocess_image

        # All-white image: pixel value 1.0 after /255
        img = Image.new("RGB", (224, 224), color=(255, 255, 255))
        result = _preprocess_image(img)
        # After normalization, values should not be in [0, 255]
        assert result.max() < 10.0  # Normalized values are small
        assert result.min() > -10.0


class TestCompareClipEmbeddings:
    """Tests for compare_clip_embeddings."""

    def test_identical_embeddings_near_one(self) -> None:
        """Identical embeddings produce similarity ~1.0."""
        from duplicates_detector.clip import compare_clip_embeddings

        emb = tuple(np.random.randn(512).astype(np.float32).tolist())
        score = compare_clip_embeddings(emb, emb)
        assert score > 0.99

    def test_orthogonal_embeddings_near_zero(self) -> None:
        """Orthogonal embeddings produce similarity ~0.0."""
        from duplicates_detector.clip import compare_clip_embeddings

        # Create two orthogonal vectors
        a = np.zeros(512, dtype=np.float32)
        a[0] = 1.0
        b = np.zeros(512, dtype=np.float32)
        b[1] = 1.0
        score = compare_clip_embeddings(tuple(a.tolist()), tuple(b.tolist()))
        assert score < 0.01

    def test_video_sliding_window_same_length(self) -> None:
        """Two video embeddings of the same length (10 frames) compare correctly."""
        from duplicates_detector.clip import compare_clip_embeddings

        rng = np.random.RandomState(42)
        emb = rng.randn(10, 512).astype(np.float32)
        flat = tuple(emb.flatten().tolist())
        score = compare_clip_embeddings(flat, flat)
        assert score > 0.99

    def test_different_length_embeddings(self) -> None:
        """Embeddings with different frame counts use sliding window."""
        from duplicates_detector.clip import compare_clip_embeddings

        rng = np.random.RandomState(42)
        # 5 frames and 10 frames — first 5 frames identical
        base = rng.randn(5, 512).astype(np.float32)
        extra = rng.randn(5, 512).astype(np.float32)
        short = tuple(base.flatten().tolist())
        long = tuple(np.concatenate([base, extra]).flatten().tolist())
        score = compare_clip_embeddings(short, long)
        # Should find perfect match when window aligns
        assert score > 0.99

    def test_result_in_unit_range(self) -> None:
        """Result is always in [0.0, 1.0]."""
        from duplicates_detector.clip import compare_clip_embeddings

        rng = np.random.RandomState(123)
        for _ in range(10):
            a = tuple(rng.randn(512).astype(np.float32).tolist())
            b = tuple(rng.randn(512).astype(np.float32).tolist())
            score = compare_clip_embeddings(a, b)
            assert 0.0 <= score <= 1.0


class TestComputeClipEmbedding:
    """Tests for compute_clip_embedding with mocked ONNX session."""

    def _make_mock_session(self, output_dim: int = 512) -> MagicMock:
        """Create a mock ONNX session that returns a random embedding."""
        session = MagicMock()
        mock_input = MagicMock()
        mock_input.name = "pixel_values"
        mock_output = MagicMock()
        mock_output.name = "image_embeds"
        session.get_inputs.return_value = [mock_input]
        session.get_outputs.return_value = [mock_output]
        # Return a non-zero embedding
        emb = np.random.randn(1, output_dim).astype(np.float32)
        session.run.return_value = [emb]
        return session

    def test_image_embedding_shape(self, tmp_path: Path) -> None:
        """Image embedding is 512 floats."""
        from PIL import Image

        from duplicates_detector.clip import compute_clip_embedding

        img_path = tmp_path / "test.jpg"
        img = Image.new("RGB", (300, 200), color=(100, 50, 25))
        img.save(str(img_path))

        mock_session = self._make_mock_session()
        with patch("duplicates_detector.clip._get_session", return_value=mock_session):
            result = compute_clip_embedding(img_path)

        assert result is not None
        assert len(result) == 512
        # Should be L2 normalized
        norm = np.linalg.norm(result)
        np.testing.assert_allclose(norm, 1.0, atol=1e-5)

    def test_video_embedding_shape(self, tmp_path: Path) -> None:
        """Video embedding is 5120 floats (10 frames x 512)."""
        from PIL import Image

        from duplicates_detector.clip import compute_clip_embedding

        video_path = tmp_path / "test.mp4"
        video_path.touch()

        # Mock _extract_video_frames to return 10 PIL images
        mock_frames = [Image.new("RGB", (224, 224), color=(i * 20, i * 10, i * 5)) for i in range(10)]
        mock_session = self._make_mock_session()

        with (
            patch("duplicates_detector.clip._get_session", return_value=mock_session),
            patch("duplicates_detector.clip._extract_video_frames", return_value=mock_frames),
        ):
            result = compute_clip_embedding(video_path, is_video=True, duration=120.0)

        assert result is not None
        assert len(result) == 5120  # 10 * 512

    def test_video_no_duration_returns_none(self, tmp_path: Path) -> None:
        """Video with no duration returns None."""
        from duplicates_detector.clip import compute_clip_embedding

        video_path = tmp_path / "test.mp4"
        video_path.touch()
        mock_session = self._make_mock_session()

        with patch("duplicates_detector.clip._get_session", return_value=mock_session):
            result = compute_clip_embedding(video_path, is_video=True, duration=None)

        assert result is None

    def test_broken_image_returns_none(self, tmp_path: Path) -> None:
        """Unreadable image file returns None."""
        from duplicates_detector.clip import compute_clip_embedding

        broken_path = tmp_path / "broken.jpg"
        broken_path.write_bytes(b"not a real image")
        mock_session = self._make_mock_session()

        with patch("duplicates_detector.clip._get_session", return_value=mock_session):
            result = compute_clip_embedding(broken_path)

        assert result is None
