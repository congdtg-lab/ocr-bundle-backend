Xin lỗi, có thể bạn chưa thấy rõ phần nội dung đầy đủ.
Dưới đây là **TOÀN BỘ nội dung README.md mới**, trình bày rõ ràng – bạn chỉ cần **copy → paste** vào file README.md trong GitHub.

---

# 📦 Knowledge File Builder — OCR Backend (Vercel Edition)

Backend FastAPI sử dụng OpenAI Vision để OCR PDF và xuất ra một **ZIP bundle** chuẩn cho assistant “Knowledge File Builder Pro — Backend Edition”.

Hỗ trợ:

* OCR từng trang PDF bằng GPT-4o / GPT-4o-mini
* Xuất text → `raw_text.md`
* Lưu metadata → `structure.json`
* Lưu cảnh báo OCR → `ocr_warnings.txt`
* Xuất ảnh từng trang → PNG
* Tạo toàn bộ bundle dưới dạng ZIP

---

# 🚀 Deploy trên Vercel

## 1️⃣ Yêu cầu file trong repo

Repo cần có các file sau:

```
main.py
requirements.txt
vercel.json
README.md
```

Xóa các file KHÔNG cần thiết:

```
Procfile
.python-version
```

## 2️⃣ Deploy

1. Vào [https://vercel.com](https://vercel.com)
2. “Add New Project” → chọn repo này
3. Deploy
4. Trong Project Settings → Environment Variables, thêm:

```
OPENAI_API_KEY=sk-xxxx
```

5. Redeploy nếu cần

---

# 🛠 API Endpoints

## 🔹 Health check

```
GET /health
```

Kết quả:

```
{"status": "ok"}
```

---

## 🔹 OCR PDF (Upload PDF)

```
POST /ocr/pdf
Content-Type: multipart/form-data
file=<PDF>
```

Phản hồi:

* ZIP file trực tiếp (`application/zip`)
* Assistant sẽ nhận được file ZIP

---

# 📁 Cấu trúc ZIP đầu ra

```
bundle.zip
 ├── docs/
 │    ├── raw_text.md
 │    ├── structure.json
 │    └── ocr_warnings.txt
 │
 ├── media/
 │   └── images/
 │        ├── page_1.png
 │        ├── page_2.png
 │        └── ...
 │
 └── tables/
      └── README.txt  (placeholder)
```

---

# 🤖 OpenAPI Schema dành cho ChatGPT Actions

Dùng schema này để gắn backend vào Assistant:

```
openapi: 3.1.0
info:
  title: Knowledge File Builder OCR Backend
  version: 1.0.0

servers:
  - url: https://<your-project>.vercel.app

paths:
  /ocr/pdf:
    post:
      operationId: ocr_pdf_upload
      summary: Upload a PDF file and receive OCR ZIP bundle.
      requestBody:
        required: true
        content:
          multipart/form-data:
            schema:
              type: object
              required:
                - file
              properties:
                file:
                  type: string
                  format: binary
      responses:
        "200":
          description: ZIP OCR bundle
          content:
            application/zip:
              schema:
                type: string
                format: binary
```

---

# 🧪 Test sau deploy

## Kiểm tra health:

```
https://<project>.vercel.app/health
```

## Kiểm tra OCR bằng upload thực tế (Postman hoặc Assistant):

```
POST https://<project>.vercel.app/ocr/pdf
```

---

# ✔️ Ghi chú quan trọng

* Vercel giới hạn upload 10MB → nếu PDF lớn, Assistant nên chuyển sang mode gửi **URL PDF**
* Toàn bộ xử lý sử dụng `/tmp` → phù hợp serverless
* Không có viewer → chỉ trả ZIP

---

# 完 (Hết)

---

Nếu bạn muốn:
👉 Tôi có thể xuất **toàn bộ backend thành 1 file ZIP** để bạn tải về.
