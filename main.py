import os
import uuid
import shutil
import fitz  # PyMuPDF
import zipfile
import tempfile
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests

# =========================
# CONFIG
# =========================
BASE_URL = os.getenv("RAILWAY_PUBLIC_DOMAIN", "http://localhost:8000")
if BASE_URL.startswith("http"):
    BASE_URL = BASE_URL.rstrip("/")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# Pydantic model (URL Mode)
# =========================
class OCRUrlRequest(BaseModel):
    file_url: str


# =========================
# Helper: Convert PDF to Images
# =========================
def pdf_to_images(pdf_path, output_folder):
    doc = fitz.open(pdf_path)
    image_paths = []

    for i, page in enumerate(doc):
        pix = page.get_pixmap(dpi=200)
        img_path = os.path.join(output_folder, f"media/images/page_{i+1}.png")
        os.makedirs(os.path.dirname(img_path), exist_ok=True)
        pix.save(img_path)
        image_paths.append(img_path)

    return image_paths


# =========================
# Helper: Fake Vision OCR (placeholder)
# =========================
def run_vision_ocr_on_image(image_path):
    """
    Placeholder OCR logic.
    Bạn đang dùng GPT-4o Vision ở bản thật, nhưng ở backend mẫu này
    mình giữ placeholder cho phù hợp.

    Bạn sẽ thay bằng code OCR thực tế của bạn.
    """
    return f"OCR placeholder for {os.path.basename(image_path)}\n"


# =========================
# Build OCR Bundle (ZIP)
# =========================
def build_bundle(pdf_path):
    session_id = str(uuid.uuid4())
    workdir = os.path.join("/tmp", f"ocr_{session_id}")
    docs_dir = os.path.join(workdir, "docs")
    tables_dir = os.path.join(workdir, "tables")
    media_dir = os.path.join(workdir, "media")

    os.makedirs(docs_dir, exist_ok=True)
    os.makedirs(tables_dir, exist_ok=True)
    os.makedirs(media_dir, exist_ok=True)

    # 1. Convert PDF → Images
    image_paths = pdf_to_images(pdf_path, workdir)

    # 2. OCR từng ảnh
    raw_text = ""
    structure = []
    warnings = []

    for idx, img in enumerate(image_paths):
        try:
            text = run_vision_ocr_on_image(img)
            raw_text += f"\n\n# Page {idx+1}\n{text}"

            structure.append({
                "page": idx + 1,
                "image": img,
                "text_length": len(text)
            })

        except Exception as e:
            warnings.append(f"Page {idx+1}: OCR error {str(e)}")

    # 3. Save docs
    with open(os.path.join(docs_dir, "raw_text.md"), "w", encoding="utf-8") as f:
        f.write(raw_text)

    import json
    with open(os.path.join(docs_dir, "structure.json"), "w", encoding="utf-8") as f:
        json.dump(structure, f, ensure_ascii=False, indent=2)

    with open(os.path.join(docs_dir, "ocr_warnings.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(warnings))

    # 4. Create ZIP
    zip_filename = f"ocr_bundle_{session_id}.zip"
    zip_path = os.path.join("/tmp", zip_filename)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(workdir):
            for file in files:
                full_path = os.path.join(root, file)
                arcname = os.path.relpath(full_path, workdir)
                zipf.write(full_path, arcname)

    return zip_path


# =========================
# API: OCR via URL
# =========================
@app.post("/ocr/pdf")
async def ocr_pdf_url(payload: OCRUrlRequest):
    file_url = payload.file_url

    # 1. Download PDF
    try:
        response = requests.get(file_url, timeout=15)
        response.raise_for_status()
        pdf_bytes = response.content
    except Exception:
        raise HTTPException(status_code=400, detail="Unable to download file_url")

    # 2. Save temp PDF
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(pdf_bytes)
        pdf_path = tmp.name

    # 3. Build OCR ZIP bundle
    zip_path = build_bundle(pdf_path)
    zip_filename = os.path.basename(zip_path)

    # 4. Build URL for user to download ZIP
    download_url = f"{BASE_URL}/files/{zip_filename}"

    return {"download_url": download_url}


# =========================
# Serve ZIP files
# =========================
@app.get("/files/{filename}")
async def download_file(filename: str):
    file_path = os.path.join("/tmp", filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path, media_type="application/zip", filename=filename)


# =========================
# Health check
# =========================
@app.get("/health")
async def health():
    return {"status": "ok"}
