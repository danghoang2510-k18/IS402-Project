# Chuyển dữ liệu FL sang Azure Blob Storage

> Topology đã chọn: `storagedataflrf` ở East Asia chứa dữ liệu gốc, validation,
> test có nhãn, tập suy luận ngoài mẫu, `client-1`, `client-2`. Tạo thêm Storage Account `storagedataflrf2` ở **Korea Central**
> chứa `client-3`, `client-4`, `client-5`. Script kiểm tra region thật trước khi
> upload. Các container hiện có `client-3` … `client-5` trong account East Asia
> để trống; không xóa hoặc ghi đè chúng. `artifacts` dành cho model/kết quả.

## Trạng thái và phạm vi

Trước thay đổi này, `cs-training.csv` ở máy Windows; 5 file `client_*.csv` nằm trên đĩa 5 VM, còn validation/test nằm trên server VM. Chế độ `DATA_BACKEND=blob` mới cho phép **mỗi client đọc CSV của mình từ Blob** và server đọc validation/test từ Blob trong mỗi lần chạy. Các file schema/metadata nhỏ vẫn ở VM để kiểm tra SHA. Split 60/20/20 vẫn được tạo trên máy Windows; upload raw CSV là bản nguồn cloud, không có nghĩa ETL đã tự động chạy trên cloud.

## 1. Kiểm tra East Asia và tạo account Korea Central

Mở `storagedataflrf` → Overview và xác nhận **Location = East Asia**. Nếu khác, dừng script và kiểm tra lại topology. Trên Portal chọn **Create a resource → Storage account → Create** cho account thứ hai: cùng subscription/resource group `rg-fl-rf-dev`, tên duy nhất toàn Azure (chỉ chữ thường/số), **Location = Korea Central**, Standard, LRS, StorageV2. Chọn secure transfer/TLS, tắt anonymous blob access. Ghi tên vào `$kcAccount`. Kiểm tra Networking cho phép máy Windows upload và các VM đọc HTTPS 443; nếu dùng Selected networks, cấp đúng IP/subnet từng region.

| Mục | Cần xác minh |
| --- | --- |
| Overview | `storagedataflrf` thực ở East Asia và account mới thực ở Korea Central; không suy ra region từ tên container. |
| Configuration | Secure transfer required, minimum TLS 1.2 trở lên, không cho anonymous blob access. |
| Networking | Máy Windows và 6 VM đều có đường HTTPS 443 tới Blob endpoint; nếu Selected networks, kiểm tra cả East Asia và Korea Central. |

Mỗi Storage Account có endpoint HTTPS riêng. VNet peering giữa East Asia và Korea Central **không tự cấp quyền Blob**. Nếu dùng Private Endpoint, cần Private DNS và đường mạng phù hợp cho từng account trước khi chuyển chế độ.

## 2. Cấp quyền upload cho tài khoản của bạn

Cài [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows), rồi đăng nhập và chọn đúng subscription:

```powershell
az login
az account show --output table
$eaAccount = "storagedataflrf"
$kcAccount = "storagedataflrf2"
```

Tài khoản upload cần vai trò **Storage Blob Data Contributor trên cả hai Storage Account** (hoặc từng container). Quyền Owner/Contributor quản lý resource không luôn bao gồm quyền dữ liệu Blob. Trong Portal: từng Storage Account → Access control (IAM) → Add role assignment → Storage Blob Data Contributor → chọn tài khoản của bạn. Nếu không có nút cấp quyền, cần người quản trị subscription thực hiện bước này. Đợi role propagation trước khi thử upload.

## 3. Kiểm tra và upload

Từ PowerShell tại thư mục gốc dự án:

```powershell
$project = "C:\Users\ACER\Documents\ChatGPT\Project Cloud"
& "$project\deployment\azure\upload_dataset_blob.ps1" -EastAsiaAccount $eaAccount -KoreaCentralAccount $kcAccount -ValidateOnly
& "$project\deployment\azure\upload_dataset_blob.ps1" -EastAsiaAccount $eaAccount -KoreaCentralAccount $kcAccount
```

Trước khi chạy script upload, chạy `python scripts/prepare_external_inference.py` để chuẩn bị `cs-test.csv` không nhãn. Script dùng lại `client-1`, `client-2` tại East Asia, tạo `client-3` … `client-5` tại Korea Central, và tạo `fl-source`, `fl-eval`, `fl-inference` tại East Asia. Nó kiểm tra SHA của 14 file, gồm raw `cs-test.csv` ở `fl-source` và CSV suy luận đã điền median cùng metadata ở `fl-inference`. Blob đã tồn tại được tải tạm để đối chiếu SHA; nếu giống thì bỏ qua, nếu khác thì dừng và không ghi đè. `artifacts` chưa được script thay đổi. File `results/blob_upload_metrics.csv` ghi `operation` (`uploaded` hoặc `verified_existing`) và Storage Account để tách hai region; thời gian của `verified_existing` là thời gian tải xuống để kiểm tra, không phải thời gian upload. Xem [data-split.md](data-split.md) để phân biệt test có nhãn với test ngoài mẫu.

Kiểm tra bằng Azure CLI:

```powershell
az storage blob list --account-name $eaAccount --container-name fl-eval --auth-mode login --output table
az storage blob list --account-name $eaAccount --container-name client-1 --auth-mode login --output table
az storage blob list --account-name $kcAccount --container-name client-3 --auth-mode login --output table
```

## 4. Cấp Managed Identity cho sáu VM

Trong từng VM → Identity → System assigned → On → Save. Ghi lại Object (principal) ID. Trên account **East Asia**, cấp **Storage Blob Data Reader** cho `vm-fl-client-1` tại `client-1`, `vm-fl-client-2` tại `client-2`, và `vm-fl-server` tại `fl-eval`. Trên account **Korea Central**, cấp Reader cho `vm-fl-client-3`/`4`/`5` chỉ tại container tương ứng. Không cấp client quyền `fl-source` hay `fl-eval`. Role assignment có thể mất vài phút để hiệu lực.

Nếu dùng CLI và có quyền tạo role assignment, scope của một container là:

```text
/subscriptions/<SUBSCRIPTION_ID>/resourceGroups/<RESOURCE_GROUP>/providers/Microsoft.Storage/storageAccounts/storagedataflrf/blobServices/default/containers/client-1
```

Client Korea Central dùng endpoint của account KC. Đo `blob_download_seconds` của từng client cùng Azure Monitor `SuccessE2ELatency`/`Egress`; việc đặt Blob gần VM sẽ thay đổi điều kiện đo I/O, nhưng không thay đổi nội dung CSV nếu SHA giữ nguyên.

## 5. Cập nhật Flower App và bật Blob mode

Chép **cả thư mục `flower-app` mới** lên server và cài lại `python -m pip install -e .` trong `~/fl-venv`; Flower chuyển FAB mới cho các SuperNode. Nếu các SuperNode dùng runtime Python riêng không cài dependency từ FAB, cài `azure-identity` và `azure-storage-blob` trong venv đó. Giữ `feature_schema.json`, `split_metadata.json`, `summary.json` trên server; mỗi client giữ `feature_schema.json`. Không cần giữ CSV trên VM để huấn luyện Blob, nhưng chỉ xóa bản cũ sau khi kiểm tra run thành công.

Trên server, trong môi trường chạy SuperLink/ServerApp:

```bash
export DATA_BACKEND=blob
export EVAL_BLOB_BASE_URL="https://storagedataflrf.blob.core.windows.net/fl-eval"
export PROJECT_DATA_ROOT=/home/azureuser/project-cloud/data
export PROJECT_RESULTS_ROOT=/home/azureuser/project-cloud/results
```

Trên từng VM client N, trong môi trường chạy SuperNode/ClientApp:

```bash
export CLIENT_ID=N
export DATA_BACKEND=blob
export CLIENT_BLOB_URL="https://ACCOUNT_THEO_REGION.blob.core.windows.net/client-N/client_N.csv"
export PROJECT_DATA_ROOT=/home/azureuser/project-cloud/data
```

Thay `ACCOUNT_THEO_REGION` bằng `storagedataflrf` cho client 1–2 và `storagedataflrf2` cho client 3–5; thay `N` bằng số client thật. Nếu SuperLink/SuperNode chạy bằng `systemd`, các biến phải nằm trong unit hoặc EnvironmentFile của service; `export` ở SSH shell khác không truyền vào service đang chạy. Restart service, rồi mới chạy `flwr run . azure-private --stream`. Không đưa SAS/key vào repo hoặc log. `DefaultAzureCredential` trên VM dùng Managed Identity; URL có SAS chỉ là phương án thay thế khi không thể cấp RBAC.

## 6. Xác minh

Kết quả Flower mới phải có `data_backend: "blob"`, `clients[*].blob_download_seconds`, `clients[*].data_bytes`, `evaluation_blob_download_seconds` và SHA partition vẫn khớp `summary.json`. Nếu Blob lỗi 403, kiểm tra identity và role Reader; nếu timeout, kiểm tra DNS/outbound 443/firewall của Storage Account. So sánh `results/blob_upload_metrics.csv` với metric Azure Monitor của Storage Account theo cùng UTC interval. Sau khi tải JSON Flower về Windows, tạo file so sánh bằng `python scripts/build_comparison.py --flower <JSON> --output results/comparison_metrics_azure.csv`.

Tài liệu Microsoft: [Blob Python với DefaultAzureCredential](https://learn.microsoft.com/en-us/azure/storage/blobs/storage-quickstart-blobs-python), [CLI upload bằng Entra login](https://learn.microsoft.com/en-us/azure/storage/blobs/authorize-data-operations-cli), [RBAC cho Blob](https://learn.microsoft.com/en-us/azure/storage/common/storage-auth-aad-rbac-portal), [Private Endpoint cho Storage](https://learn.microsoft.com/en-us/azure/storage/common/storage-private-endpoints).
