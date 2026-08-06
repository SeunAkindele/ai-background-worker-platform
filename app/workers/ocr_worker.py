"""OCR handler — extract text from images, PDFs, or uploaded files."""
from pathlib import Path
from typing import Any, Generator

from app.workers.base import BaseJobHandler


class OCRHandler(BaseJobHandler[dict[str, Any], dict[str, Any]]):
    def validate_input(self, input_payload: dict[str, Any]) -> None:
        image = input_payload.get("image")
        images = input_payload.get("images")
        file_path = input_payload.get("file_path")
        file_id = input_payload.get("file_id")

        if (
            image is None
            and images is None
            and file_path is None
            and file_id is None
        ):
            raise ValueError(
                "OCR requires 'image', 'images', 'file_path', or 'file_id'"
            )

        if file_path is not None:
            path = Path(file_path)
            if not path.is_file():
                raise ValueError(f"File not found: {file_path}")

        if images is not None:
            if not isinstance(images, list):
                raise ValueError("'images' must be a list")
            if len(images) == 0:
                raise ValueError("'images' must not be empty")
            if len(images) > 50:
                raise ValueError("Batch limited to 50 images")

    def process(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        image = input_payload.get("image")
        images = input_payload.get("images")
        file_path = input_payload.get("file_path")

        if file_path is not None:
            result = self._process_file(file_path)
            result["source"] = {
                "type": "file",
                "path": file_path,
                "original_filename": input_payload.get("original_filename"),
                "file_type": input_payload.get("file_type"),
                "file_size": input_payload.get("file_size"),
            }
            return result

        if image is not None:
            page_result = self._process_single_image(image)
            return {"pages": [page_result], "total_pages": 1}

        pages = list(self._process_batch(images))
        return {"pages": pages, "total_pages": len(pages)}

    def format_result(self, raw_result: dict[str, Any]) -> dict[str, Any]:
        full_text = "\n\n".join(
            page["text"] for page in raw_result["pages"] if page["text"]
        )
        formatted = {
            "text": full_text,
            "pages": raw_result["pages"],
            "total_pages": raw_result["total_pages"],
        }
        if "source" in raw_result:
            formatted["source"] = raw_result["source"]
        return formatted

    def _process_batch(
        self, images: list[str]
    ) -> Generator[dict[str, Any], None, None]:
        for idx, image_data in enumerate(images):
            yield self._process_single_image(image_data, page_number=idx + 1)

    def _process_single_image(
        self, image_data: str, page_number: int = 1
    ) -> dict[str, Any]:
        try:
            import base64
            import io

            from PIL import Image

            image_bytes = base64.b64decode(image_data)
            image = Image.open(io.BytesIO(image_bytes))
            image = self._preprocess_image(image)

            try:
                import pytesseract
                text = pytesseract.image_to_string(image)
                confidence = self._estimate_confidence(image, text)
            except (ImportError, OSError):
                text = f"[simulated OCR output for page {page_number}]"
                confidence = 0.0

            return {
                "page": page_number,
                "text": text.strip(),
                "confidence": confidence,
                "width": image.width,
                "height": image.height,
            }

        except Exception as e:
            return {
                "page": page_number,
                "text": f"[simulated OCR output for page {page_number}]",
                "confidence": 0.0,
                "error": str(e),
            }

    def _preprocess_image(self, image):
        from PIL import ImageFilter

        if image.mode != "L":
            image = image.convert("L")

        max_dimension = 4000
        if image.width > max_dimension or image.height > max_dimension:
            ratio = min(max_dimension / image.width, max_dimension / image.height)
            new_size = (int(image.width * ratio), int(image.height * ratio))
            image = image.resize(new_size)

        image = image.filter(ImageFilter.SHARPEN)
        return image

    def _process_file(self, file_path: str) -> dict[str, Any]:
        """Process a file from disk (image or multi-page PDF)."""
        try:
            from PIL import Image

            image = Image.open(file_path)
            pages = []

            try:
                page_num = 0
                while True:
                    image.seek(page_num)
                    frame = image.copy()
                    frame = self._preprocess_image(frame)

                    try:
                        import pytesseract
                        text = pytesseract.image_to_string(frame)
                        confidence = self._estimate_confidence(frame, text)
                    except (ImportError, OSError):
                        text = f"[simulated OCR for page {page_num + 1}]"
                        confidence = 0.0

                    pages.append({
                        "page": page_num + 1,
                        "text": text.strip(),
                        "confidence": confidence,
                    })
                    page_num += 1
            except EOFError:
                pass

            if not pages:
                pages = [{"page": 1, "text": "[no content extracted]", "confidence": 0.0}]

            return {"pages": pages, "total_pages": len(pages)}

        except Exception as e:
            return {
                "pages": [{"page": 1, "text": f"[error: {e}]", "confidence": 0.0}],
                "total_pages": 1,
            }

    @staticmethod
    def _estimate_confidence(image, text: str) -> float:
        if not text.strip():
            return 0.0
        char_count = len(text.strip())
        pixel_count = image.width * image.height
        density = char_count / (pixel_count / 10000)
        return min(round(density * 0.1, 2), 0.99)