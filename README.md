
# OCR Bundle Backend (Railway-ready)

Backend FastAPI dùng OpenAI Vision để OCR PDF và tạo ZIP bundle.

## Chạy local

```bash
export OPENAI_API_KEY="sk-..."
export BASE_URL="http://localhost:8000"
uvicorn main:app --reload --port 8000
```

## Endpoint

- POST `/ocr/pdf` : upload PDF, trả về JSON gồm zip_url và metadata
- GET `/files/{filename}` : tải file ZIP

## Deploy lên Railway

1. Push project này lên GitHub.
2. Trên Railway, tạo project mới từ repo.
3. Set biến môi trường:
   - `OPENAI_API_KEY`
   - `BASE_URL` = URL public của Railway (ví dụ: `https://your-app.up.railway.app`)
4. Start command: `uvicorn main:app --host 0.0.0.0 --port 8000`
