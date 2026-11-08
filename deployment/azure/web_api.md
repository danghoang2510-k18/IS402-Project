# Triển khai giao diện và API trên vm-fl-server

Điều kiện: lần chạy Flower mới đã tạo `results/models/run_<RUN_ID>/{model.json,forest.npz}` và JSON kết quả có `model_artifact`. Lần chạy cũ chỉ có metrics nên không đủ cho `/predict`. Web có ba trang; các phần giám sát VM, chi phí và non-IID vẫn cần số đo riêng theo rubric.

## 1. Build giao diện trên Windows

```powershell
$project = "C:\Users\ACER\Documents\ChatGPT\Project Cloud"
Set-Location "$project\web"
pnpm install --frozen-lockfile
pnpm exec tsc --noEmit
pnpm build
```

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

Lấy thư mục chứa `model.json` từ output; thay `run_REPLACE_WITH_RUN_ID` trong unit bằng đúng tên thư mục. Sau đó:

```bash
sudo cp ~/fl-credit-api.service /etc/systemd/system/fl-credit-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now fl-credit-api
sudo systemctl status fl-credit-api --no-pager
curl -f http://127.0.0.1:8080/healthz
curl -f http://127.0.0.1:8080/dashboard
```

`GET /dashboard` đọc JSON FL và hàng `centralized,best_f1` từ CSV; trả metric đã lọc, không trả dữ liệu khách hàng. Nếu `model_matches_loaded_artifact=false`, kết quả FL trên trang có thể thuộc run khác model đang phục vụ. Kiểm tra `MODEL_DIR` và JSON trước khi trình diễn.

## 4. Phục vụ web qua Nginx để thử riêng tư

```bash
sudo apt-get update
sudo apt-get install -y nginx
sudo mkdir -p /var/www/fl-credit
sudo cp -a ~/project-cloud/web-dist/. /var/www/fl-credit/
sudo cp ~/fl-credit.nginx.conf /etc/nginx/sites-available/fl-credit
sudo ln -s /etc/nginx/sites-available/fl-credit /etc/nginx/sites-enabled/fl-credit
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
