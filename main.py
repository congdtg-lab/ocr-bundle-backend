import os
import io
import uuid
import base64
import zipfile
import json
from typing import List, Optional

import fitz  # PyMuPDF
from PIL import Image
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from openai import OpenAI

# ===== ENVIRONMENT =====
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is not set")

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

client = OpenAI(api_key=OPENAI_API_KEY)

# ===== DIRECTORIES =====
UPLOAD_DIR = "uploads"
BUNDLE_DIR = "bundles"
WORK_DIR = "work"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(BUNDLE_DIR, exist_ok=True)
os.makedirs(WORK_DIR, exist_ok=True)

# ===== FASTAPI APP =====
app = FastAPI(title="OCR Bundle API", version="1.0.0")


# ============================================
# PDF → Images bằng PyMuPDF (KHÔNG cần Poppler)
# ============================================
def pdf_to_images(pdf_path: str) -> List[Image.Image]:
    doc = fitz.open(pdf_path)
    imgs = []

    for page in doc:
        pix = page.get_pixmap(dpi=300)
        img_bytes = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_bytes))
        imgs.append(img)

    doc.close()
    return imgs


# ============================================
# Helper: PIL image → Base64 PNG
# ============================================
def pil_to_base64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64}"


# ============================================
# OCR bằng GPT-4o
# ============================================
def ocr_page_with_vision(img: Image.Image) -> str:
    img_b64 = pil_to_base64(img)

    prompt = (
        "Bạn là engine OCR. Hãy TRÍCH XUẤT CHÍNH XÁC toàn bộ văn bản có trong ảnh.\n"
        "- Ngôn ngữ: Tiếng Việt + tiếng Anh.\n"
        "- Không tóm tắt, không dịch.\n"
        "- Không bỏ bớt nội dung.\n"
        "- Trả về văn bản thuần (plain text).\n"
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


# ============================================
# Build OCR bundle ZIP
# ============================================
def build_bundle(pdf_path: str, job_id: str) -> dict:
    workdir = os.path.join(WORK_DIR, job_id)
    docs_dir = os.path.join(workdir, "docs")
    tables_dir = os.path.join(workdir, "tables")
    media_dir = os.path.join(workdir, "media", "images")

    os.makedirs(docs_dir, exist_ok=True)
    os.makedirs(tables_dir, exist_ok=True)
    os.makedirs(media_dir, exist_ok=True)

    pages = pdf_to_images(pdf_path)
    results = []

    for idx, img in enumerate(pages, start=1):
        print(f"[{job_id}] OCR trang {idx}/{len(pages)}")
        warning = None

        try:
            text = ocr_page_with_vision(img)
        except Exception as e:
            text = ""
            warning = f"OCR error: {e}"

        results.append(
            {
                "page_number": idx,
                "text": text,
                "text_length": len(text),
                "warning": warning,
            }
        )

        img_path = os.path.join(media_dir, f"page_{idx:03d}.png")
        img.save(img_path, format="PNG")

    # ---- Save raw text ----
    raw_text_path = os.path.join(docs_dir, "raw_text.md")
    total_chars = 0

    with open(raw_text_path, "w", encoding="utf-8") as f:
        for item in results:
            f.write(f"<!-- Page {item['page_number']} -->\n")
            f.write(item["text"])
            f.write("\n\n")
            total_chars += item["text_length"]

    # ---- Structure JSON ----
    struct_path = os.path.join(docs_dir, "structure.json")
    with open(struct_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "pages": [
                    {
                        "page_number": item["page_number"],
                        "text_length": item["text_length"],
                        "has_warning": item["warning"] is not None,
                    }
                    for item in results
                ]
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    # ---- Warnings ----
    warn_path = os.path.join(docs_dir, "ocr_warnings.txt")
    with open(warn_path, "w", encoding="utf-8") as f:
        for item in results:
            if item["warning"]:
                f.write(f"Trang {item['page_number']}: {item['warning']}\n")

    # ---- Sample table placeholder ----
    table_path = os.path.join(tables_dir, "table_001.json")
    with open(table_path, "w", encoding="utf-8") as f:
        json.dump(
            {"tables": [], "note": "Chưa implement nhận diện bảng."},
            f,
            ensure_ascii=False,
            indent=2,
        )

    # ---- ZIP toàn bộ ----
    zip_name = f"{job_id}.zip"
    zip_path = os.path.join(BUNDLE_DIR, zip_name)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(workdir):
            for filename in files:
                full = os.path.join(root, filename)
                rel = os.path.relpath(full, workdir)
                z.write(full, arcname=rel)

    return {
        "zip_name": zip_name,
        "zip_path": zip_path,
        "page_count": len(results),
        "total_chars": total_chars,
        "warnings": [r["warning"] for r in results if r["warning"]],
    }


# ============================================
# ROUTES
# ============================================

@app.post("/ocr/pdf")
async def ocr_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File phải là PDF")

    job_id = str(uuid.uuid4())
    pdf_path = os.path.join(UPLOAD_DIR, f"{job_id}.pdf")

    with open(pdf_path, "wb") as f:
        f.write(await file.read())

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
    path = os.path.join(BUNDLE_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Không tìm thấy file")

    return FileResponse(path, media_type="application/zip", filename=filename)


@app.get("/health")
async def health():
    return {"status": "ok"}
