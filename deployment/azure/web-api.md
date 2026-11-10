# Triển khai giao diện và API trên vm-fl-server

Trạng thái 2026-11-10: API và Nginx preview đã chạy trên server; Nginx chỉ nghe `127.0.0.1:8081`. Đã kiểm tra cả ba trang trong trình duyệt, assets, `/api/healthz`, `/api/dashboard`, và `POST /api/predict` qua proxy. API trả `run_id` và `model_run_id` dưới dạng chuỗi để JavaScript giữ đúng Flower ID 64 bit. Trên Windows mở `ssh -N -L 8081:127.0.0.1:8081 vm-fl-server`, rồi vào `http://127.0.0.1:8081`. Chưa mở web công khai; cần domain và TLS trước khi cấu hình HTTPS 443.

Điều kiện: model của một run Flower đã được publish lên container `artifacts` và có `latest-iid.json`. Xem [model-artifacts.md](model-artifacts.md) để đưa run hiện tại lên Blob và bật tự upload/tự cập nhật. Web có ba trang; các phần giám sát VM, chi phí và non-IID vẫn cần số đo riêng theo rubric.

## 1. Build giao diện trên Windows

```powershell
$project = "C:\Users\ACER\Documents\ChatGPT\Project Cloud"
Set-Location "$project\web"
pnpm install --frozen-lockfile
pnpm exec tsc --noEmit
pnpm build
```

Nếu không có `pnpm` nhưng `web/node_modules` đã được cài bằng pnpm, dùng
`npm.cmd run build` mà không chạy `npm install` trên thư mục đó.

## 2. Chép mã API, metrics và web lên server

Trong PowerShell:

```powershell
ssh vm-fl-server "mkdir -p /home/azureuser/project-cloud/results/protocol_v1/seed42_iid_clients5_trees20 /home/azureuser/project-cloud/web-dist"
scp "$project\flower-app\fl_app\api.py" vm-fl-server:/home/azureuser/project-cloud/flower-app/fl_app/api.py
scp "$project\results\protocol_v1\seed42_iid_clients5_trees20\test_metrics.csv" vm-fl-server:/home/azureuser/project-cloud/results/protocol_v1/seed42_iid_clients5_trees20/test_metrics.csv
scp -r "$project\web\dist\." vm-fl-server:/home/azureuser/project-cloud/web-dist/
scp "$project\deployment\azure\fl-credit-api.service.example" vm-fl-server:/home/azureuser/fl-credit-api.service
scp "$project\deployment\azure\fl-credit.nginx.conf.example" vm-fl-server:/home/azureuser/fl-credit.nginx.conf
```

JSON FL được sinh trên VM khi chạy Flower, không chép JSON cũ từ Windows đè lên. Kiểm tra `model_artifact` trong JSON trỏ đến đúng model mới.

## 3. Cài và bật API

Trên `vm-fl-server`:

```bash
cd ~/project-cloud/flower-app
source ~/fl-venv/bin/activate
python -m pip install -e .
python -c 'import json; from pathlib import Path; p=Path.home()/"project-cloud/results/flower_seed42_iid_clients5.json"; r=json.loads(p.read_text()); print(r.get("model_artifact", "CHUA_CO_MODEL"))'
```

Unit hiện dùng `ARTIFACT_BLOB_BASE_URL` và `MODEL_MODE=iid`, nên không cần thay run ID sau mỗi lần huấn luyện. Sau đó:

```bash
sudo cp ~/fl-credit-api.service /etc/systemd/system/fl-credit-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now fl-credit-api
sudo systemctl status fl-credit-api --no-pager
curl -f http://127.0.0.1:8080/healthz
curl -f http://127.0.0.1:8080/dashboard
```

`GET /dashboard` đọc FL metrics của đúng run đang phục vụ từ Blob và hàng `centralized,best_f1` từ CSV trên server; trả metric đã lọc, không trả dữ liệu khách hàng. `model_matches_loaded_artifact` phải là `true`.

## 4. Phục vụ web qua Nginx để thử riêng tư

```bash
sudo apt-get update
sudo apt-get install -y nginx
sudo mkdir -p /var/www/fl-credit
sudo cp -a ~/project-cloud/web-dist/. /var/www/fl-credit/
sudo cp ~/fl-credit.nginx.conf /etc/nginx/sites-available/fl-credit
sudo ln -sfn /etc/nginx/sites-available/fl-credit /etc/nginx/sites-enabled/fl-credit
sudo nginx -t
sudo systemctl reload nginx
curl -I http://127.0.0.1:8081/
```

Trên Windows, mở SSH tunnel rồi xem `http://127.0.0.1:8081`:

```powershell
ssh -N -L 8081:127.0.0.1:8081 vm-fl-server
```

Tunnel này chỉ dùng để xác minh UI/API. Nếu muốn người khác truy cập, cấu hình domain, TLS hợp lệ và Nginx 443, rồi mở NSG TCP 443 cho nhóm xem demo. Không mở 8080 hoặc 8081 ra Internet. Chứng chỉ Flower không dùng làm chứng chỉ HTTPS của web.

## 5. Kiểm tra kết quả

```bash
curl -s http://127.0.0.1:8080/healthz
curl -s http://127.0.0.1:8080/dashboard
curl -sS -X POST http://127.0.0.1:8080/predict -H 'Content-Type: application/json' -d '{"features":{"RevolvingUtilizationOfUnsecuredLines":0.15,"age":52,"NumberOfTime30-59DaysPastDueNotWorse":0,"DebtRatio":0.37,"MonthlyIncome":5400,"NumberOfOpenCreditLinesAndLoans":8,"NumberOfTimes90DaysLate":0,"NumberRealEstateLoansOrLines":1,"NumberOfTime60-89DaysPastDueNotWorse":0,"NumberOfDependents":0}}'
```

Đối chiếu xác suất, nhãn, threshold và run ID giữa `curl` với trang Dự đoán. Nếu service lỗi, xem `journalctl -u fl-credit-api -n 100 --no-pager`. Nếu trang web hiện nhưng API lỗi, kiểm tra `curl` loopback và Nginx `location /api/`.
