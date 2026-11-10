# Model Flower trên Blob và API tự cập nhật

Kiến trúc: mỗi run lưu bất biến tại `storagedataflrf/artifacts/runs/<run_id>/` gồm `model.json`, `forest.npz`, `metrics.json`. Sau khi upload và tải lại kiểm tra SHA đủ ba file, ServerApp cập nhật `artifacts/latest-iid.json`. API trên server dùng Managed Identity đọc pointer mỗi 30 giây; khi có run mới, nó tải và kiểm tra toàn bộ model trước khi đổi bản đang phục vụ. Run `non-iid` có pointer riêng `latest-non-iid.json`, không thay model IID dùng cho web.

## 1. IAM

Trong `storagedataflrf` → container `artifacts` → IAM, cấp **Storage Blob Data Contributor** cho system-assigned managed identity của `vm-fl-server`. Quyền `Storage Blob Data Reader` ở `fl-eval` vẫn giữ. ServerApp cần quyền ghi artifact và pointer; API cùng VM dùng identity này để đọc. Nếu sau này chuyển API sang VM khác, chỉ cấp Reader tại `artifacts` cho identity của VM API.

## 2. Cập nhật mã trên server

Trên PowerShell ở thư mục dự án:

```powershell
$project = "C:\Users\ACER\Documents\ChatGPT\Project Cloud"
$bundle = Join-Path $env:TEMP 'flower-app-update.tar.gz'
tar -czf $bundle -C "$project\flower-app" pyproject.toml fl_app
scp -o ConnectTimeout=15 -o ConnectionAttempts=3 $bundle vm-fl-server:/home/azureuser/flower-app-update.tar.gz
ssh -o ConnectTimeout=15 vm-fl-server 'mkdir -p ~/project-cloud/scripts'
scp -o ConnectTimeout=15 -o ConnectionAttempts=3 "$project\scripts\publish_model_artifact.py" vm-fl-server:/home/azureuser/project-cloud/scripts/publish_model_artifact.py
```

Trên server:

```bash
tar -xzf ~/flower-app-update.tar.gz -C ~/project-cloud/flower-app
source ~/fl-venv/bin/activate
cd ~/project-cloud/flower-app
python -m pip install -e .
```

## 3. Đưa run đã hoàn thành lên Blob, không cần huấn luyện lại

Run `6558643287244268762` đã có model trên server. Sau khi IAM Contributor có hiệu lực, trên server:

```bash
source ~/fl-venv/bin/activate
python ~/project-cloud/scripts/publish_model_artifact.py \
  --result ~/project-cloud/results/flower_seed42_iid_clients5.json \
  --container-url https://storagedataflrf.blob.core.windows.net/artifacts
```

Output phải có `run_id: 6558643287244268762`, `mode: iid`, ba SHA và prefix `runs/6558643287244268762`. Trên Portal, container `artifacts` phải có ba blob trong prefix đó và `latest-iid.json`. Nếu quyền bị từ chối, kiểm tra identity và role ở bước 1; không dùng account key/SAS.

## 4. Tự upload ở các run sau

Trong **môi trường tiến trình SuperLink/ServerApp**, đặt:

```bash
source ~/project-cloud/flower_server_env.sh
echo "$ARTIFACT_BLOB_BASE_URL"
```

File `flower_server_env.sh` nằm trong `deployment/azure/` của dự án và cần được chép lên server tại đường dẫn trên. Source file này trong cả shell khởi động SuperLink và shell chạy `flwr run`. Nếu SuperLink chạy bằng systemd, thêm biến vào unit/EnvironmentFile rồi restart. `export` trong một SSH shell khác không tác động đến tiến trình đã chạy. Với mỗi run thành công, ServerApp tự lưu model/metrics trên VM, upload lên Blob, kiểm tra SHA và cập nhật pointer của mode tương ứng. Nếu upload lỗi, run báo lỗi và pointer cũ giữ nguyên để API tiếp tục dùng bản hợp lệ trước đó.

## 5. API lấy model mới nhất

API không cần `MODEL_DIR` cố định. Cấu hình service theo `fl-credit-api.service.example`:

```text
ARTIFACT_BLOB_BASE_URL=https://storagedataflrf.blob.core.windows.net/artifacts
MODEL_MODE=iid
MODEL_REFRESH_SECONDS=30
```

Sau khi khởi động/restart API, thử:

```bash
curl -f http://127.0.0.1:8080/healthz
curl -f http://127.0.0.1:8080/dashboard
```

`/healthz` phải hiện `model_source: blob` và run ID của pointer. Mỗi request sau mốc 30 giây sẽ kiểm tra pointer; nếu đổi run, API chỉ chuyển sau khi tải và kiểm tra SHA/model thành công. Nếu Blob tạm lỗi sau khi đã có model, API phục vụ bản đã xác minh trước đó và `/healthz` báo `refresh_warning`. Với instance API mới chưa tải được model nào, API trả 503. `GET /dashboard` lấy FL metrics cùng run đang phục vụ; centralized metrics vẫn đọc từ `test_metrics.csv` trên server.

## 6. Kiểm tra và giới hạn

- Giữ `model.json`, `forest.npz`, `metrics.json` theo từng run; không upload artifact vào `web/dist`.
- Pointer chọn **run hoàn tất gần nhất được publish** trong từng mode. Nếu muốn phê duyệt thủ công model trước khi phục vụ web, cần tách bước publish và promote; cơ chế hiện tại tự promote sau khi kiểm tra kỹ thuật.
- Run `6558643287244268762` đã được publish lên Blob trên Azure; API trên `vm-fl-server` đã trả `/healthz` với `model_source: blob`, `/dashboard` khớp model và `/predict` cùng run ID. Chưa có run thứ hai để xác nhận chuyển model tự động ngoài thực tế; bài kiểm thử local đã mô phỏng cập nhật và từ chối artifact lỗi.

Tham khảo: [Azure Python upload Blob](https://learn.microsoft.com/en-us/azure/storage/blobs/storage-blob-upload-python), [quyền Blob qua Entra ID](https://learn.microsoft.com/en-us/azure/storage/common/storage-auth-aad-rbac-portal).
