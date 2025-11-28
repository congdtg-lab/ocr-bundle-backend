import os
import uuid
import shutil
import fitz   # PyMuPDF
import zipfile
import tempfile
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI

# =========================
# INITIAL SETUP
# =========================

app = FastAPI()

# Allow all CORS (for ChatGPT actions)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# =========================
# MODELS
# =========================

class OCRResponse(BaseModel):
    download_url: str


# =========================
# ROOT + HEALTH
# =========================

@app.get("/")
async def root():
    return {"status": "ok", "service": "OCR Bundle Backend (Vercel)"}


@app.get("/health")
async def health():
    return {"status": "ok"}


# =========================
# HELPER — RUN OCR VISION
# =========================

async def run_vision_ocr(image_bytes: bytes, page_number: int):
    """
    Calls OpenAI Vision to generate OCR text.
    Returns pure text.
    """
    result = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are an OCR engine. Extract ALL visible text accurately."},
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": f"OCR page {page_number}. Return plain text only."},
                    {"type": "input_image", "image_url": f"data:image/png;base64,{image_bytes.decode('latin1')}"}
                ]
            }
        ]
    )

    return result.choices[0].message["content"]


# =========================
# BUILD OCR ZIP BUNDLE
# =========================

def build_zip_bundle(base_dir: str, zip_path: str):
    """Zip toàn bộ bundle."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(base_dir):
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, base_dir)
                z.write(full, rel)


# =========================
# OCR PDF ENDPOINT
# =========================

@app.post("/ocr/pdf", response_model=OCRResponse)
async def ocr_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF.")

    # Create temp workspace (serverless-compatible)
    work_id = str(uuid.uuid4())
    tmp_root = os.path.join("/tmp", work_id)
    docs_dir = os.path.join(tmp_root, "docs")
    media_dir = os.path.join(tmp_root, "media", "images")
    tables_dir = os.path.join(tmp_root, "tables")

    os.makedirs(docs_dir, exist_ok=True)
    os.makedirs(media_dir, exist_ok=True)
    os.makedirs(tables_dir, exist_ok=True)

    pdf_path = os.path.join(tmp_root, "input.pdf")

    # Save uploaded file
    with open(pdf_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Load PDF
    doc = fitz.open(pdf_path)

    raw_text_all = ""
    warnings = []

    # Iterate pages
    for i, page in enumerate(doc):
        page_num = i + 1

        # Render page → PNG bytes
        pix = page.get_pixmap(dpi=200)
        img_bytes = pix.tobytes("png")

        # Save PNG file
        img_out = os.path.join(media_dir, f"page_{page_num}.png")
        pix.save(img_out)

        # OCR via OpenAI Vision
        try:
            ocr_text = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "OCR engine. Extract ALL text accurately."},
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": f"OCR page {page_num}. Return plain text only."},
                            {
                                "type": "input_image",
                                "image_url": f"data:image/png;base64,{img_bytes.decode('latin1')}"
                            }
                        ]
                    }
                ]
            ).choices[0].message["content"]

        except Exception as e:
            ocr_text = ""
            warnings.append(f"Page {page_num} OCR error: {str(e)}")

        raw_text_all += f"\n\n# PAGE {page_num}\n" + ocr_text

    # Save raw_text.md
    with open(os.path.join(docs_dir, "raw_text.md"), "w", encoding="utf-8") as f:
        f.write(raw_text_all)

    # Save structure.json
    with open(os.path.join(docs_dir, "structure.json"), "w", encoding="utf-8") as f:
        f.write('{"pages": ' + str(doc.page_count) + '}')

    # Save warnings
    with open(os.path.join(docs_dir, "ocr_warnings.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(warnings))

    # Build ZIP
    zip_out = os.path.join(tmp_root, "bundle.zip")
    build_zip_bundle(tmp_root, zip_out)

    # Return downloadable URL
    # Vercel serves static files via /api or /files – we use on-demand FileResponse fallback
    return FileResponse(zip_out, filename="ocr_bundle.zip")
