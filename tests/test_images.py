"""Tests for image file detection in agent responses."""

from __future__ import annotations

from pathlib import Path

from pykoclaw_matrix.images import detect_image_paths, mime_for_path


class TestDetectImagePaths:
    """Tests for detect_image_paths()."""

    def test_no_paths(self) -> None:
        assert detect_image_paths("Just plain text") == []

    def test_detects_png(self, tmp_path: Path) -> None:
        img = tmp_path / "output.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        text = f"I saved the image to {img}"
        result = detect_image_paths(text)
        assert len(result) == 1
        assert result[0] == img

    def test_detects_jpeg(self, tmp_path: Path) -> None:
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
        text = f"Here's the photo: {img}"
        result = detect_image_paths(text)
        assert len(result) == 1
        assert result[0] == img

    def test_detects_backtick_wrapped(self, tmp_path: Path) -> None:
        img = tmp_path / "output.png"
        img.write_bytes(b"\x89PNG" + b"\x00" * 100)
        text = f"Saved to `{img}`"
        result = detect_image_paths(text)
        assert len(result) == 1

    def test_detects_quoted_path(self, tmp_path: Path) -> None:
        img = tmp_path / "output.png"
        img.write_bytes(b"\x89PNG" + b"\x00" * 100)
        text = f'Saved to "{img}"'
        result = detect_image_paths(text)
        assert len(result) == 1

    def test_multiple_images(self, tmp_path: Path) -> None:
        img1 = tmp_path / "a.png"
        img2 = tmp_path / "b.jpg"
        img1.write_bytes(b"\x89PNG" + b"\x00" * 100)
        img2.write_bytes(b"\xff\xd8" + b"\x00" * 100)
        text = f"Created {img1} and {img2}"
        result = detect_image_paths(text)
        assert len(result) == 2

    def test_deduplicates(self, tmp_path: Path) -> None:
        img = tmp_path / "output.png"
        img.write_bytes(b"\x89PNG" + b"\x00" * 100)
        text = f"Saved to {img}. Check {img} for the result."
        result = detect_image_paths(text)
        assert len(result) == 1

    def test_ignores_nonexistent(self) -> None:
        text = "Saved to /tmp/nonexistent_xyz_12345.png"
        assert detect_image_paths(text) == []

    def test_ignores_non_image_extensions(self, tmp_path: Path) -> None:
        txt = tmp_path / "notes.txt"
        txt.write_text("hello")
        text = f"See {txt}"
        assert detect_image_paths(text) == []

    def test_ignores_relative_paths(self, tmp_path: Path) -> None:
        img = tmp_path / "output.png"
        img.write_bytes(b"\x89PNG" + b"\x00" * 100)
        # Only absolute paths are detected
        text = "Saved to output.png"
        assert detect_image_paths(text) == []

    def test_supported_extensions(self, tmp_path: Path) -> None:
        for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"]:
            img = tmp_path / f"test{ext}"
            img.write_bytes(b"\x00" * 100)
        text = " ".join(
            str(tmp_path / f"test{ext}")
            for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"]
        )
        result = detect_image_paths(text)
        assert len(result) == 6

    def test_empty_string(self) -> None:
        assert detect_image_paths("") == []


class TestMimeForPath:
    """Tests for mime_for_path()."""

    def test_png(self) -> None:
        assert mime_for_path(Path("image.png")) == "image/png"

    def test_jpeg(self) -> None:
        assert mime_for_path(Path("photo.jpg")) == "image/jpeg"

    def test_jpeg_long(self) -> None:
        assert mime_for_path(Path("photo.jpeg")) == "image/jpeg"

    def test_gif(self) -> None:
        assert mime_for_path(Path("anim.gif")) == "image/gif"

    def test_webp(self) -> None:
        assert mime_for_path(Path("pic.webp")) == "image/webp"

    def test_unknown(self) -> None:
        assert mime_for_path(Path("data.qzx")) == "application/octet-stream"
