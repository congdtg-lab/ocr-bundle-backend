import os
import io
import uuid
import base64
import zipfile
import json
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from pdf2image import convert_from_path
from PIL import Image
from openai import OpenAI

# === ENV ===
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is not set")

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
client = OpenAI(api_key=OPENAI_API_KEY)

# === DIRECTORIES ===
UPLOAD_DIR = "uploads"
BUNDLE_DIR = "bundles"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(BUNDLE_DIR, exist_ok=True)

# === FASTAPI APP ===
app = FastAPI(title="OCR Bundle API", version="1.0.0")

# === UTILS ===
def pdf_to_images(pdf_path: str, dpi: int = 300) -> List[Image.Image]:
    return convert_from_path(pdf_path, dpi=dpi)

def pil_to_base64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64}"

def ocr_page_with_vision(img: Image.Image) -> str:
    img_b64 = pil_to_base64(img)
    prompt = (
        "Bạn là engine OCR. Hãy TRÍCH XUẤT CHÍNH XÁC toàn bộ văn bản có trong ảnh.\n"
        "- Ngôn ngữ chính là tiếng Việt (có thể lẫn tiếng Anh).\n"
        "- Giữ nguyên nội dung, không dịch.\n"
        "- Không tóm tắt, không bỏ bớt.\n"
        "- Không thêm chú thích.\n"
        "- Trả về CHỈ văn bản thuần (plain text), không markdown.\n"
    )

    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": img_b64}},
                ],
            }
        ],
        max_tokens=4000,
    )

    return resp.choices[0].message.content or ""

def build_bundle(pdf_path: str, job_id: str) -> dict:
    workdir = os.path.join("work", job_id)
    docs_dir = os.path.join(workdir, "docs")
    tables_dir = os.path.join(workdir, "tables")
    media_dir = os.path.join(workdir, "media", "images")

    os.makedirs(docs_dir, exist_ok=True)
    os.makedirs(tables_dir, exist_ok=True)
    os.makedirs(media_dir, exist_ok=True)

    pages = pdf_to_images(pdf_path)
    page_results: List[dict] = []

    for idx, page_img in enumerate(pages, start=1):
        print(f"[{job_id}] OCR trang {idx}/{len(pages)}")

        warning: Optional[str] = None
        try:
            text = ocr_page_with_vision(page_img)
        except Exception as e:
            warning = f"OCR error: {e}"
            text = ""

        page_results.append(
            {
                "page_number": idx,
                "text": text,
                "warning": warning,
                "text_length": len(text),
            }
        )

        img_path = os.path.join(media_dir, f"page_{idx:03d}.png")
        page_img.save(img_path, format="PNG")

    raw_text_path = os.path.join(docs_dir, "raw_text.md")
    total_chars = 0
    with open(raw_text_path, "w", encoding="utf-8") as f:
        for p in page_results:
            f.write(f"<!-- Page {p['page_number']} -->\n")
            f.write(p["text"])
            f.write("\n\n")
            total_chars += len(p["text"])

    structure = {
        "pages": [
            {
                "page_number": p["page_number"],
                "text_length": p["text_length"],
                "has_warning": p["warning"] is not None,
            }
            for p in page_results
        ]
    }
    structure_path = os.path.join(docs_dir, "structure.json")
    with open(structure_path, "w", encoding="utf-8") as f:
        json.dump(structure, f, ensure_ascii=False, indent=2)

    warnings_path = os.path.join(docs_dir, "ocr_warnings.txt")
    with open(warnings_path, "w", encoding="utf-8") as f:
        for p in page_results:
            if p["warning"]:
                f.write(f"Trang {p['page_number']}: {p['warning']}\n")

    sample_table_meta = {
        "tables": [],
        "note": "Chưa implement nhận diện bảng chi tiết."
    }
    table_path = os.path.join(tables_dir, "table_001.json")
    with open(table_path, "w", encoding="utf-8") as f:
        json.dump(sample_table_meta, f, ensure_ascii=False, indent=2)

    zip_name = f"{job_id}.zip"
    zip_path = os.path.join(BUNDLE_DIR, zip_name)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(workdir):
            for name in files:
                full_path = os.path.join(root, name)
                rel_path = os.path.relpath(full_path, workdir)
                z.write(full_path, arcname=rel_path)

    return {
        "zip_path": zip_path,
        "zip_name": zip_name,
        "page_count": len(page_results),
        "total_chars": total_chars,
        "warnings": [p["warning"] for p in page_results if p["warning"]],
    }

# === ROUTES ===
@app.post("/ocr/pdf")
async def ocr_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File phải là PDF")

    job_id = str(uuid.uuid4())
    pdf_path = os.path.join(UPLOAD_DIR, f"{job_id}.pdf")

    with open(pdf_path, "wb") as f:
        content = await file.read()
        f.write(content)

    meta = build_bundle(pdf_path, job_id)
    zip_url = f"{BASE_URL}/files/{meta['zip_name']}"

    return {
        "job_id": job_id,
        "zip_url": zip_url,
        "page_count": meta["page_count"],
        "total_chars": meta["total_chars"],
        "warnings": meta["warnings"],
    }

@app.get("/files/{filename}")
async def download_file(filename: str):
    file_path = os.path.join(BUNDLE_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Không tìm thấy file")
    return FileResponse(
        file_path,
        media_type="application/zip",
        filename=filename
    )

@app.get("/health")
async def health():
    return {"status": "ok"}
