# Federated Random Forest dự đoán rủi ro tín dụng trên Azure

Dự án so sánh Random Forest huấn luyện tập trung với học liên kết (FL) bằng Flower trên bộ dữ liệu **Give Me Some Credit**. Hệ thống có 1 server, 5 client trên hai region Azure, dữ liệu từ Blob Storage, mô hình được lưu lên Blob, FastAPI phục vụ suy luận và web React gọi API.

> Mô hình phục vụ bài tập và trình diễn kỹ thuật, không dùng để ra quyết định cấp tín dụng. Dữ liệu và kết quả của mỗi lần chạy cần được đối chiếu bằng SHA và run ID, không lấy kết quả cũ làm bằng chứng cho lần triển khai mới.

## Trạng thái hiện tại

- Đã chạy FL-IID trên Azure với 5 client, tổng 100 cây, test 30.000 hàng. Run đã quan sát: `6558643287244268762`, ROC-AUC `0.866876`, average precision `0.407101`, F1 `0.443339`.
- Model của run trên đã được publish vào container `artifacts`. API trên `vm-fl-server` đọc model từ Blob; `/healthz`, `/dashboard`, `/predict` và web qua Nginx/SSH tunnel đã được kiểm tra.
- Chưa kiểm chứng **run thứ hai tự thay model đang phục vụ** trên Azure. Web hiện là preview riêng tư, chưa có public HTTPS. Còn cần thu thập Azure Monitor, latency liên vùng, chi phí và minh chứng báo cáo.
- Dự án theo **nhánh Phân tích dữ liệu** (hàng 34–37, sheet `Bài tập Lớn` của rubric). Xem [đối chiếu metric](deployment/azure/rubric-metrics.md). FL non-IID trên Azure là thí nghiệm mở rộng, chưa được xác nhận.

## Kiến trúc và giao thức

```text
Local: cs-training.csv -> split seed 42 -> Blob Storage
  East Asia: storagedataflrf (fl-source, fl-eval, client-1/2, artifacts)
  Korea Central: storagedataflrf2 (client-3/4/5)
  5 Flower SuperNode --TLS/private IP--> SuperLink + ServerApp (East Asia)
  ServerApp -> artifacts/runs/<run_id>/ + latest-iid.json
  FastAPI (Managed Identity) -> Nginx -> React web
```

Từ `cs-training.csv` có 150.000 hàng có nhãn, notebook tạo split phân tầng **90.000 train / 30.000 validation / 30.000 test**, `seed=42`. Median chỉ fit trên train; hai mô hình dùng cùng 10 đặc trưng và cùng test. Train được chia thành 5 phần IID không giao nhau, mỗi client fit 20 cây; server ghép thành 100 cây. Baseline tập trung fit 100 cây trên toàn bộ train. Cấu hình RF cố định: `max_depth=10`, `min_samples_leaf=5`, `max_features="sqrt"`, `class_weight=None`. Chọn ngưỡng trên validation trước khi tính metric test. `cs-test.csv` không có nhãn, chỉ dùng suy luận ngoài mẫu. Chi tiết xem [data-split.md](deployment/azure/data-split.md).

## Cấu trúc mã nguồn

```text
data/                   CSV nguồn local và experiments/split_seed_42/ sinh ra
notebooks/
  centralized_random_forest.ipynb               EDA, tuning và baseline cố định 100 cây
  federated_random_forest.ipynb                 Giải thích aggregation local và đọc phép đo FL Azure
flower-app/
  pyproject.toml         Cấu hình Flower 1.42.0, IID/5 client/20 cây
  fl_app/                ClientApp, ServerApp, Blob, model, đánh giá, FastAPI
scripts/                 Chuẩn bị suy luận, ghép metric, publish run cũ
web/                     React + TypeScript + Vite, build ra web/dist/
deployment/azure/        Script upload, cấu hình service/Nginx, runbook
results/                 Kết quả local và bằng chứng, không commit
tests/                   Kiểm thử giao thức và artifact
```

Các CSV nguồn, split và kết quả nằm ngoài Git theo `.gitignore`. Máy triển khai mới phải có đúng `data/cs-training.csv` và `data/cs-test.csv`, rồi tạo lại split. Không ghép JSON Flower cũ với split khác SHA.

## Bước 1: chuẩn bị và tạo split trên Windows

Cần Python **>=3.11,<4.0**, OpenSSH, Azure CLI, Node.js và pnpm. Dùng PowerShell, thay `$project` nếu đặt repo nơi khác:

```powershell
$project = 'C:\Users\ACER\Documents\ChatGPT\Project Cloud'
Set-Location $project
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-centralized.txt
python -m jupyter lab
```

Chạy `notebooks/centralized_random_forest.ipynb` trên local để có EDA, Grid Search và baseline cố định khớp Flower Azure. Notebook import trực tiếp hai module dùng chung `flower-app/fl_app/protocol.py` và `evaluation.py` để giữ cùng split/metric; **không cần cài Flower hoặc chạy SuperLink/SuperNode trên local**. Giữ cấu trúc thư mục dự án và mở Jupyter từ thư mục gốc. Kết quả nằm ở `results/centralized_seed42_fixed/`; nếu có JSON Azure tại `results/azure_traffic_new_run/`, ô cuối tự tạo `comparison_metrics_azure.csv` sau khi kiểm SHA và cấu hình.

Run Flower trên Azure và JSON `results/azure_traffic_new_run/flower_seed42_iid_clients5.json` là **kết quả FL thực**. `notebooks/federated_random_forest.ipynb` là tài liệu thực nghiệm bổ trợ: minh họa 5 Client huấn luyện/ghép cây trên local và hiển thị báo cáo truyền thông đã đo trên Azure. **Không cần chạy lại notebook FL để lấy hoặc xác nhận metric của run cloud.** Nếu muốn tái tạo mô phỏng local đầy đủ, sau khi chạy notebook FL có thể dùng:

```powershell
python scripts/prepare_external_inference.py
python scripts/build_comparison.py
python -m unittest discover -s tests -v
```

Kiểm tra `data/experiments/split_seed_42/` có `feature_schema.json`, `split_metadata.json`, `validation.csv`, `test.csv`, `iid/clients_5/summary.json` và `client_1.csv` đến `client_5.csv`. `results/comparison_metrics.csv` lúc này là baseline và **FL mô phỏng local**. Kết quả Azure sẽ được ghép riêng ở bước 6.

## Bước 2: tạo Azure resources

Các thao tác Portal, quota, CIDR và CA chi tiết ở [runbook Azure](deployment/azure/deployment-guide.md). Topology cần tái tạo:

1. Tạo resource group, ví dụ `rg-fl-rf-dev`; kiểm tra **Total Regional vCPUs**, quota VM family và Public IP ở **East Asia** và **Korea Central**. Gói Student không có một số VM cố định cho mọi region.
2. Tạo hai VNet theo region, CIDR không chồng lấn, subnet và peering **hai chiều Connected**. VM Korea Central không gắn trực tiếp vào VNet East Asia.
3. Tạo `vm-fl-server`, `vm-fl-client-1`, `-2` ở East Asia; `vm-fl-client-3` đến `-5` ở Korea Central. Chỉ server cần public IP. Ghi **private IP server thực tế**.
4. NSG server: TCP 22 từ IP quản trị, TCP 8000 từ subnet client của hai VNet. NSG client: TCP 22 từ private IP/subnet server để SSH qua `ProxyJump`. `Source port ranges` đặt `*`; `Destination port ranges` đặt `22` hoặc `8000`.
5. Đảm bảo các VM gọi HTTPS 443 ra PyPI và Blob. Subnet có **Private subnet / no default outbound access** cần outbound rõ ràng như NAT Gateway; peering không cấp internet.
6. Tạo StorageV2 `storagedataflrf` ở East Asia và `storagedataflrf2` ở Korea Central, container private, HTTPS/TLS bắt buộc. Tên account phải duy nhất toàn Azure; nếu đổi tên thì sửa URL trong môi trường và service.

Trong `~/.ssh/config` trên Windows, alias `vm-fl-server` dùng public IP; mỗi `vm-fl-client-N` dùng private IP và `ProxyJump vm-fl-server`. Thử `ssh vm-fl-server hostname` và `ssh vm-fl-client-3 hostname` trước khi SCP. Ví dụ cấu hình ở [runbook, bước 5](deployment/azure/deployment-guide.md#5-ssh-từ-windows-vào-6-vm).

```sshconfig
Host vm-fl-server
    HostName <SERVER_PUBLIC_IP>
    User azureuser
    IdentityFile C:/Users/ACER/.ssh/<PRIVATE_KEY>

Host vm-fl-client-1
    HostName <CLIENT_1_PRIVATE_IP>
    User azureuser
    IdentityFile C:/Users/ACER/.ssh/<PRIVATE_KEY>
    ProxyJump vm-fl-server

# Tạo tương tự cho client-2 đến client-5 với private IP riêng.
```

## Bước 3: upload Blob và cấp IAM

Tài khoản chạy upload cần **Storage Blob Data Contributor** trên hai Storage Account. Quyền quản lý resource `Owner` không mặc nhiên cho phép thao tác dữ liệu Blob bằng `--auth-mode login`. Bật **System assigned Managed Identity** cho sáu VM:

| VM | Quyền Blob |
| --- | --- |
| Client 1–2 | Reader chỉ tại `client-1`/`client-2` tương ứng trên `storagedataflrf` |
| Client 3–5 | Reader chỉ tại `client-3`/`client-4`/`client-5` tương ứng trên `storagedataflrf2` |
| Server | Reader tại `fl-eval`, Contributor tại `artifacts` trên `storagedataflrf` |

```powershell
Set-Location $project
az login
az account show --output table
.\deployment\azure\upload_dataset_blob.ps1 -ProjectRoot $project `
  -EastAsiaAccount storagedataflrf -KoreaCentralAccount storagedataflrf2 -ValidateOnly
.\deployment\azure\upload_dataset_blob.ps1 -ProjectRoot $project `
  -EastAsiaAccount storagedataflrf -KoreaCentralAccount storagedataflrf2
```

Script kiểm SHA, region và blob đã có trước khi ghi; khác SHA thì dừng, không ghi đè. Log đo upload/kiểm tra ở `results/blob_upload_metrics.csv`. `fl-source`, `fl-eval`, `fl-inference`, `client-1/2` ở East Asia; `client-3/4/5` ở Korea Central. Client không được đọc test có nhãn. Hướng dẫn kiểm tra CLI và lỗi 403 ở [blob-data.md](deployment/azure/blob-data.md).

## Bước 4: cài Flower trên sáu VM

Trên **mỗi VM Ubuntu**, sau khi outbound HTTPS thông:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip openssl curl
python3 --version
python3 -m venv ~/fl-venv
source ~/fl-venv/bin/activate
python -m pip install --upgrade pip
python -m pip install 'flwr==1.42.0'
mkdir -p ~/project-cloud/data/experiments/split_seed_42 ~/project-cloud/certs
```

Python VM phải thỏa `>=3.11,<4.0`. Trên Windows, chép app và **chỉ metadata nhỏ**; server đọc validation/test từ Blob, client đọc partition riêng từ Blob:

```powershell
$split = Join-Path $project 'data\experiments\split_seed_42'
ssh vm-fl-server 'mkdir -p ~/project-cloud/data/experiments/split_seed_42/iid/clients_5 ~/project-cloud/results'
scp -r (Join-Path $project 'flower-app') vm-fl-server:/home/azureuser/project-cloud/
scp (Join-Path $split 'feature_schema.json') (Join-Path $split 'split_metadata.json') `
  vm-fl-server:/home/azureuser/project-cloud/data/experiments/split_seed_42/
scp (Join-Path $split 'iid\clients_5\summary.json') `
  vm-fl-server:/home/azureuser/project-cloud/data/experiments/split_seed_42/iid/clients_5/
scp (Join-Path $project 'deployment\azure\flower_server_env.sh') `
  vm-fl-server:/home/azureuser/project-cloud/flower_server_env.sh
foreach ($id in 1..5) {
  $vm = "vm-fl-client-$id"
  ssh $vm 'mkdir -p ~/project-cloud/data/experiments/split_seed_42'
  if ($LASTEXITCODE -ne 0) { throw "SSH lỗi: $vm" }
  scp (Join-Path $split 'feature_schema.json') `
    "${vm}:/home/azureuser/project-cloud/data/experiments/split_seed_42/"
  if ($LASTEXITCODE -ne 0) { throw "SCP lỗi: $vm" }
}
```

Trên server: `source ~/fl-venv/bin/activate`, `cd ~/project-cloud/flower-app`, `python -m pip install -e .`. Khi cập nhật app, chép **cả `pyproject.toml` và `fl_app`**, cài lại; Flower chuyển app tới SuperNode. CSV cũ trên VM chỉ nên xóa sau khi đã xác nhận chạy Blob thành công.

Tạo CA/server certificate trên server, SAN chứa **private IP server**:

```bash
SERVER_PRIVATE_IP='<SERVER_PRIVATE_IP>'
cd ~/project-cloud/certs
openssl req -x509 -newkey rsa:3072 -nodes -days 90 -sha256 \
  -keyout ca.key -out ca.crt -subj '/CN=FL-Lab-CA' \
  -addext 'basicConstraints=critical,CA:TRUE' \
  -addext 'keyUsage=critical,keyCertSign,cRLSign'
openssl req -new -newkey rsa:3072 -nodes \
  -keyout server.key -out server.csr -subj '/CN=vm-fl-server'
printf 'subjectAltName=IP:%s,IP:127.0.0.1\nextendedKeyUsage=serverAuth\n' \
  "$SERVER_PRIVATE_IP" > server.ext
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key \
  -CAcreateserial -out server.crt -days 90 -sha256 -extfile server.ext
chmod 600 ca.key server.key
openssl x509 -in server.crt -noout -ext subjectAltName
```

Chỉ chép `ca.crt` tới client, giữ `ca.key` và `server.key` trên server. Trên Windows:

```powershell
$ca = Join-Path $env:TEMP 'fl-ca.crt'
scp -o ConnectTimeout=15 -o ConnectionAttempts=3 `
  vm-fl-server:/home/azureuser/project-cloud/certs/ca.crt $ca
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $ca)) {
  throw 'Chưa tải được ca.crt từ server'
}
foreach ($id in 1..5) {
  $vm = "vm-fl-client-$id"
  ssh $vm 'mkdir -p ~/project-cloud/certs'
  if ($LASTEXITCODE -ne 0) { throw "SSH lỗi: $vm" }
  scp $ca "${vm}:/home/azureuser/project-cloud/certs/ca.crt"
  if ($LASTEXITCODE -ne 0) { throw "SCP CA lỗi: $vm" }
}
```

Certificate Flower không phải certificate HTTPS của web. Khi hết hạn 90 ngày phải cấp lại server certificate và phân phối CA mới nếu thay CA. Xem thêm [runbook, bước 9](deployment/azure/deployment-guide.md#9-tạo-ca-certificate-và-chép-ca-tới-client).

## Bước 5: chạy FL-IID trên Azure

Trên server, thêm profile vào `~/.flwr/config.toml`:

```toml
[superlink.azure-private]
address = "127.0.0.1:8000"
root-certificates = "/home/azureuser/project-cloud/certs/ca.crt"
```

Ở terminal SSH **thứ nhất trên server**, source môi trường trong chính shell khởi động SuperLink:

```bash
source ~/fl-venv/bin/activate
source ~/project-cloud/flower_server_env.sh
: "${ARTIFACT_BLOB_BASE_URL:?Chưa cấu hình container artifacts}"
printf 'Model output: %s\n' "$ARTIFACT_BLOB_BASE_URL"
flower-superlink \
  --host 0.0.0.0 --port 8000 \
  --ssl-ca-certfile ~/project-cloud/certs/ca.crt \
  --ssl-certfile ~/project-cloud/certs/server.crt \
  --ssl-keyfile ~/project-cloud/certs/server.key
```

Trên **mỗi client**, terminal riêng, đặt ID và URL của chính nó. Ví dụ client 1:

```bash
source ~/fl-venv/bin/activate
export CLIENT_ID=1
export DATA_BACKEND=blob
export PROJECT_DATA_ROOT=/home/azureuser/project-cloud/data
export CLIENT_BLOB_URL='https://storagedataflrf.blob.core.windows.net/client-1/client_1.csv'
export SERVER_PRIVATE_IP='<SERVER_PRIVATE_IP>'
printf 'client=%s blob=%s server=%s\n' "$CLIENT_ID" "$CLIENT_BLOB_URL" "$SERVER_PRIVATE_IP"
test -f "$PROJECT_DATA_ROOT/experiments/split_seed_42/feature_schema.json"
test -f ~/project-cloud/certs/ca.crt
flower-supernode \
  --superlink "${SERVER_PRIVATE_IP}:8000" \
  --root-certificates ~/project-cloud/certs/ca.crt \
  --host 127.0.0.1 --port 9094
```

Thay `CLIENT_ID`, tên container/file đúng VM; client 1–2 dùng account `storagedataflrf`, client 3–5 dùng `storagedataflrf2`. `SERVER_PRIVATE_IP` là IP của **server**, không phải của client. Không dán liền hai lệnh `export`: lỗi `invalid literal for int() with base 10: '2export'` là biến `CLIENT_ID` bị nối sai. Sửa môi trường phải khởi động lại SuperNode.

Sau khi đủ 5 node kết nối, terminal SSH **thứ hai trên server**:

```bash
source ~/fl-venv/bin/activate
source ~/project-cloud/flower_server_env.sh
: "${ARTIFACT_BLOB_BASE_URL:?Chưa cấu hình container artifacts}"
cd ~/project-cloud/flower-app
mkdir -p "$PROJECT_RESULTS_ROOT"
set -o pipefail
flwr run . azure-private --stream 2>&1 | tee "$PROJECT_RESULTS_ROOT/flower_console_iid.log"
flwr ls azure-private
```

JSON `~/project-cloud/results/flower_seed42_iid_clients5.json` phải có `data_backend="blob"`, 5 client, 100 cây, 30.000 test rows và `model_artifact`. Kiểm tra log không có `Exit Code: 201`. `set -o pipefail` tránh `tee` che mã lỗi, nhưng vẫn phải xem JSON/log. ServerApp publish `model.json`, `forest.npz`, `metrics.json` vào `artifacts/runs/<run_id>/`, kiểm SHA rồi cập nhật `latest-iid.json`. Xem [model-artifacts.md](deployment/azure/model-artifacts.md) nếu cần publish một run đã hoàn tất từ trước.

Container đầu ra không truyền bằng tham số `flower-superlink`: file `flower_server_env.sh` đã export `ARTIFACT_BLOB_BASE_URL=https://storagedataflrf.blob.core.windows.net/artifacts`. ServerApp đọc biến này và ghi bằng Managed Identity của `vm-fl-server`; identity cần quyền `Storage Blob Data Contributor` trên container `artifacts`. Shell khởi động SuperLink và shell chạy `flwr run` đều phải source file môi trường này.

Tạo bảng so sánh với **JSON Azure mới** trên Windows:

```powershell
scp -o ConnectTimeout=15 -o ConnectionAttempts=3 `
  vm-fl-server:/home/azureuser/project-cloud/results/flower_seed42_iid_clients5.json `
  (Join-Path $project 'results\flower_seed42_iid_clients5.json')
Set-Location $project
python scripts/build_comparison.py `
  --flower results/flower_seed42_iid_clients5.json `
  --output results/comparison_metrics_azure.csv
```

Script chỉ ghép khi SHA nguồn/split/schema và cấu hình RF khớp. `numeric_payload_bytes` là byte mảng số của cây, **không phải** tổng traffic mạng. Để đo byte thực của vòng Flower theo từng client, chạy lại ServerApp mới và làm theo [communication-cost.md](deployment/azure/communication-cost.md); JSON kết quả có mốc UTC đầu/cuối vòng. Thời gian fit local và thời gian cả vòng Flower trên VM khác cấu hình không phải phép đo speedup đồng điều kiện.

## Bước 6: triển khai API và web

API trên server dùng Managed Identity đọc `artifacts/latest-iid.json`, kiểm SHA của model và metrics. Sau mốc mặc định 30 giây, request tiếp theo kiểm tra pointer; chỉ chuyển model khi artifact mới hợp lệ. Nếu Blob tạm lỗi mà đã có model, API giữ bản hợp lệ cũ. Xem [model-artifacts.md](deployment/azure/model-artifacts.md) và [web-api.md](deployment/azure/web-api.md).

Trên Windows, cài Node.js và pnpm; `npm install` từng lỗi `EUNSUPPORTEDPROTOCOL workspace:*` với dependency hiện có, nên dùng pnpm để cài mới:

```powershell
Set-Location (Join-Path $project 'web')
pnpm install --frozen-lockfile
pnpm exec tsc --noEmit
pnpm build
Set-Location $project
ssh vm-fl-server 'mkdir -p ~/project-cloud/results/protocol_v1/seed42_iid_clients5_trees20 ~/project-cloud/web-dist'
scp (Join-Path $project 'results\protocol_v1\seed42_iid_clients5_trees20\test_metrics.csv') `
  vm-fl-server:/home/azureuser/project-cloud/results/protocol_v1/seed42_iid_clients5_trees20/test_metrics.csv
scp -r (Join-Path $project 'web\dist\.') vm-fl-server:/home/azureuser/project-cloud/web-dist/
scp (Join-Path $project 'deployment\azure\fl-credit-api.service.example') `
  vm-fl-server:/home/azureuser/fl-credit-api.service
scp (Join-Path $project 'deployment\azure\fl-credit.nginx.conf.example') `
  vm-fl-server:/home/azureuser/fl-credit.nginx.conf
```

Trên server, sau khi `flower-app` mới đã được cài:

```bash
sudo cp ~/fl-credit-api.service /etc/systemd/system/fl-credit-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now fl-credit-api
curl -f http://127.0.0.1:8080/healthz
curl -f http://127.0.0.1:8080/dashboard
sudo apt-get update
sudo apt-get install -y nginx
sudo mkdir -p /var/www/fl-credit
sudo cp -a ~/project-cloud/web-dist/. /var/www/fl-credit/
sudo cp ~/fl-credit.nginx.conf /etc/nginx/sites-available/fl-credit
sudo ln -sfn /etc/nginx/sites-available/fl-credit /etc/nginx/sites-enabled/fl-credit
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
curl -I http://127.0.0.1:8081/
```

Nginx mẫu nghe `127.0.0.1:8081`, API nghe `127.0.0.1:8080`. Trên Windows mở PowerShell riêng:

```powershell
ssh -N -L 18081:127.0.0.1:8081 vm-fl-server
```

Mở `http://127.0.0.1:18081/`; kiểm tra Tổng quan, Dự đoán, So sánh và một request dự đoán thật theo [web-api.md, mục 5](deployment/azure/web-api.md#5-kiểm-tra-kết-quả). `model_run_id` trả dưới dạng **chuỗi** để JavaScript giữ đúng Flower ID 64 bit. Không chép `forest.npz`, CSV raw hay khóa lên `web/dist`. Để demo cho người ngoài cần domain, TLS hợp lệ và reverse proxy trên 443; không mở 8080/8081 trực tiếp ra Internet.

## Minh chứng rubric và lỗi thường gặp

Theo [monitoring.md](deployment/azure/monitoring.md), lưu cùng `run_id` và khoảng UTC: CPU/network/disk của sáu VM, Blob ingress/egress và latency, TCP delay giữa hai region, API request/error/latency, Cost Analysis và quota. `comparison_metrics_azure.csv` là **metric mô hình**, không thay metric hạ tầng. Nếu báo cáo ETL tự động, cần log một pipeline ETL thực; notebook chia file trên local chưa chứng minh ETL cloud tự động.

| Triệu chứng | Kiểm tra |
| --- | --- |
| Không tạo/start VM | Quota **Total Regional vCPUs**, quota family và `ZoneAllocationFailed` (capacity khác quota). |
| `curl pypi.org` timeout | Subnet outbound, NAT/default outbound, NSG TCP 443; DNS ra IP chưa chứng minh HTTPS thông. |
| SSH client timeout nhưng server vào được | Private IP client, `ProxyJump`, peering, NSG TCP 22, VM status; dùng `ssh -v -o ConnectTimeout=10 vm-fl-client-3`. |
| SCP timeout ngắt quãng | Kiểm tra `ssh vm-fl-server hostname`, thêm `-o ConnectTimeout=15 -o ConnectionAttempts=3`, kiểm `$LASTEXITCODE`. |
| Blob 403 dù tài khoản là Owner | Gán đúng **Storage Blob Data Reader/Contributor** cho account/VM identity ở container và chờ RBAC có hiệu lực. |
| SuperNode `Connection attempt failed` | `--superlink` phải dùng **private IP server**, kiểm tra TCP 8000, NSG, certificate SAN. |
| Flower `Exit Code: 201` | Đọc `Client replies failed`, log client, `CLIENT_ID`, SHA/schema và quyền Blob. |
| Web mở nhưng API lỗi | `systemctl status fl-credit-api`, `journalctl -u fl-credit-api -n 100`, `/healthz`, pointer Blob và Nginx `location /api/`. |

Các thao tác Azure Portal, CA, NSG, Flower và API đầy đủ nằm trong [deployment-guide.md](deployment/azure/deployment-guide.md). Resource, IAM, domain và chi phí phải được xác nhận trong subscription triển khai lại.
