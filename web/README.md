# FRF Lab web

Giao diện React/Vite được chuyển từ bản Figma Make do nhóm cung cấp. Ba trang: Tổng quan, Dự đoán và So sánh. Số liệu so sánh được đọc từ API; giao diện không chứa kết quả mô phỏng.

## Chạy trên máy phát triển

Mở hai terminal tại thư mục gốc dự án. API cần model artifact do một lần chạy Flower mới xuất ra:

```powershell
$env:MODEL_DIR = "C:\path\to\results\models\run_<RUN_ID>"
$env:PROJECT_RESULTS_ROOT = "C:\Users\ACER\Documents\ChatGPT\Project Cloud\results"
$env:PYTHONPATH = "C:\Users\ACER\Documents\ChatGPT\Project Cloud\flower-app"
python -m uvicorn fl_app.api:app --host 127.0.0.1 --port 8080
```

```powershell
cd "C:\Users\ACER\Documents\ChatGPT\Project Cloud\web"
pnpm install --frozen-lockfile
pnpm dev
```

Mở `http://127.0.0.1:5173`. Vite chuyển `/api/*` đến FastAPI loopback. Nếu model chưa có, trang Dự đoán hiện lỗi kết nối và trang So sánh chỉ hiện những metric đã có; các giá trị này không được suy diễn từ dữ liệu mẫu của Figma.

`pnpm exec tsc --noEmit` kiểm tra TypeScript; `pnpm build` tạo `web/dist/` để Nginx phục vụ. Không chép CSV thô, chứng chỉ, `forest.npz` hoặc `model.json` vào `dist/`.

Hướng dẫn chạy trên Azure: [deployment/azure/web_api.md](../deployment/azure/web_api.md).
