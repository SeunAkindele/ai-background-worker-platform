import io
from pathlib import Path

from PIL import Image


def _make_test_png() -> bytes:
    img = Image.new("RGB", (100, 50), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_upload_file_returns_metadata(client):
    png_bytes = _make_test_png()

    response = client.post(
        "/uploads",
        data={"purpose": "ocr"},
        files={"file": ("test.png", png_bytes, "image/png")},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["original_filename"] == "test.png"
    assert data["file_type"] == "image/png"
    assert data["file_size"] == len(png_bytes)
    assert len(data["content_hash"]) == 64
    assert data["deduplicated"] is False
    assert data["purpose"] == "ocr"


def test_upload_deduplicates_same_file(client):
    png_bytes = _make_test_png()

    first = client.post(
        "/uploads",
        data={"purpose": "ocr"},
        files={"file": ("a.png", png_bytes, "image/png")},
    )
    second = client.post(
        "/uploads",
        data={"purpose": "ocr"},
        files={"file": ("b.png", png_bytes, "image/png")},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["content_hash"] == second.json()["content_hash"]
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["deduplicated"] is True


def test_create_job_with_file_id(client, celery_calls):
    png_bytes = _make_test_png()

    upload = client.post(
        "/uploads",
        data={"purpose": "ocr"},
        files={"file": ("scan.png", png_bytes, "image/png")},
    )
    assert upload.status_code == 201
    file_id = upload.json()["id"]

    job = client.post(
        "/jobs",
        json={
            "job_type": "ocr",
            "input": {"file_id": file_id},
        },
    )

    assert job.status_code == 201
    data = job.json()
    assert data["status"] == "pending"
    assert "file_path" in data["input_payload"]
    assert Path(data["input_payload"]["file_path"]).exists()
    assert data["input_payload"]["original_filename"] == "scan.png"
    assert celery_calls[-1]["args"] == [data["id"]]


def test_create_job_with_upload_one_shot(client):
    png_bytes = _make_test_png()

    response = client.post(
        "/uploads/job",
        data={"job_type": "ocr", "priority": "normal"},
        files={"file": ("invoice.png", png_bytes, "image/png")},
    )

    assert response.status_code == 201
    assert response.json()["job_type"] == "ocr"
    assert "file_path" in response.json()["input_payload"]


def test_upload_rejects_invalid_mime_for_purpose(client):
    response = client.post(
        "/uploads",
        data={"purpose": "ocr"},
        files={"file": ("song.mp3", b"fake", "audio/mpeg")},
    )
    assert response.status_code == 400


def test_get_upload_metadata(client):
    png_bytes = _make_test_png()

    upload = client.post(
        "/uploads",
        data={"purpose": "ocr"},
        files={"file": ("meta.png", png_bytes, "image/png")},
    )
    file_id = upload.json()["id"]

    response = client.get(f"/uploads/{file_id}")
    assert response.status_code == 200
    assert response.json()["id"] == file_id
    assert response.json()["original_filename"] == "meta.png"


def test_get_job_file_metadata(client):
    png_bytes = _make_test_png()

    upload = client.post(
        "/uploads",
        data={"purpose": "ocr"},
        files={"file": ("doc.png", png_bytes, "image/png")},
    )
    file_id = upload.json()["id"]

    job = client.post(
        "/jobs",
        json={"job_type": "ocr", "input": {"file_id": file_id}},
    )
    assert job.status_code == 201
    job_id = job.json()["id"]

    response = client.get(f"/jobs/{job_id}/file")
    assert response.status_code == 200
    assert response.json()["id"] == file_id
    assert response.json()["job_id"] == job_id


def test_job_rejects_mismatched_file_purpose(client):
    png_bytes = _make_test_png()

    upload = client.post(
        "/uploads",
        data={"purpose": "ocr"},
        files={"file": ("scan.png", png_bytes, "image/png")},
    )
    file_id = upload.json()["id"]

    # Transcription job cannot use an OCR-purpose file
    job = client.post(
        "/jobs",
        json={
            "job_type": "transcription",
            "input": {"file_id": file_id},
        },
    )
    assert job.status_code == 400
