# Triển khai Federated Random Forest trên Azure: từ VM đến mô hình và API

Tài liệu này ghi lại cấu hình thí nghiệm đang dùng: **1 server + 5 client**, Flower
**1.42.0**, dữ liệu Give Me Some Credit, chia **60/20/20 với seed 42**, IID 5 phần,
**20 cây/client** và **100 cây tổng hợp**. Server, client 1–2 ở **East Asia**;
client 3–5 ở **Korea Central**. Các lệnh PowerShell chạy trên máy Windows;
các lệnh Bash chạy trên VM Ubuntu với user `azureuser`.

> Thay mọi giá trị trong dấu `<...>` bằng giá trị thật trong Azure Portal.
> **Không gõ nguyên** `10.x.x.x`. IP, CIDR, khóa SSH và quota có thể khác giữa
> các subscription. Giữ nguyên split, seed, đặc trưng và cấu hình RF khi so sánh
> centralized với FL. File kết quả IID cũ chỉ có metrics; sau khi triển khai mã
> xuất mô hình ở bước 12, cần chạy lại để tạo artifact.

## 1. Kiểm tra quota và lập sơ đồ tài nguyên

1. Azure Portal → **Quotas → Compute**; lọc subscription và **East Asia**.
   Xem **Total Regional vCPUs** và **Standard Basv2 Family vCPUs**; làm tương
   tự với Korea Central. Cả hai giới hạn đều phải còn chỗ. Lần triển khai trước
   có Basv2 family **6/10** nhưng **Total Regional Cores 6/6**, nên VM mới bị
   `QuotaExceeded`. Không suy ra số VM cố định từ nhãn *Azure for Students*.
2. Dự tính số vCPU bằng `số VM × vCPU mỗi VM`. SKU trong lần chạy trước là
   `Standard_B2als_v2` (2 vCPU); 3 VM East Asia dùng 6 vCPU. Chọn SKU 1 vCPU
   hoặc Korea Central chỉ khi kiểm tra đủ quota, khả dụng SKU và RAM cho huấn luyện.
3. Kiểm tra quota **Public IP** riêng. Chỉ server cần public IP cho SSH từ máy
   cá nhân; 5 client có thể chỉ dùng private IP và SSH qua server.
4. Chuẩn bị resource group `rg-fl-rf-dev`, hai VNet với **CIDR không chồng lấn**,
   ví dụ East Asia `10.10.0.0/16`, Korea Central `10.20.0.0/16`. Ví dụ này
   không phải CIDR hiện tại của dự án; ghi CIDR thật vào bảng dưới.

| Thông số cần ghi | Giá trị trong Portal |
| --- | --- |
| East Asia VNet/subnet CIDR | `<EA_VNET_CIDR>` / `<EA_SUBNET_CIDR>` |
| Korea Central VNet/subnet CIDR | `<KC_VNET_CIDR>` / `<KC_SUBNET_CIDR>` |
| Server public/private IP | `<SERVER_PUBLIC_IP>` / `<SERVER_PRIVATE_IP>` |
| Client 1–5 private IP | `<CLIENT_1_PRIVATE_IP>` … `<CLIENT_5_PRIVATE_IP>` |
| VM SKU, vCPU, RAM từng VM | `<SKU / vCPU / RAM>` |

## 2. Tạo mạng, VM và peering trên Azure Portal

1. **Virtual networks → Create**: tạo VNet East Asia và VNet Korea Central trong
   cùng resource group. Tạo subnet cho VM ở từng VNet. Không thể chọn VNet East
   Asia khi tạo VM tại Korea Central vì VNet gắn với một region.
2. **Virtual machines → Create**: tạo `vm-fl-server`, `vm-fl-client-1`,
   `vm-fl-client-2` tại East Asia; tạo `vm-fl-client-3` đến `-5` tại Korea Central.
   Chọn Ubuntu, cùng user `azureuser`, đăng nhập bằng SSH key. Gắn server vào
   subnet East Asia và các client vào subnet tương ứng. Chỉ gắn public IP cho
   server. Ghi private IP từ **VM → Networking → Network interface → IP
   configurations**; cân nhắc đặt private IP static để địa chỉ không đổi sau
   khi VM bị deallocate.
3. **Virtual networks → VNet East Asia → Peerings → Add**: chọn VNet Korea
   Central, cho phép traffic giữa hai VNet. Kiểm tra cả hai hướng peering đều
   `Connected`. Nếu Portal không tạo chiều ngược tự động, tạo peering từ VNet
   Korea Central về East Asia. Không bật gateway transit/forwarded traffic nếu
   sơ đồ này không dùng. Peering không cấp internet outbound cho client.
4. Kiểm tra **effective routes** của NIC nếu cross-region không thông: đường
   tới CIDR VNet kia phải là `VNet peering`. CIDR hai VNet không được trùng.

## 3. NSG: SSH và Flower

Vào **Network security groups**; kiểm tra NSG đang gắn ở NIC hay subnet, vì cả
hai vị trí đều ảnh hưởng. Tạo inbound rules có priority nhỏ hơn rule deny:

| NSG | Source | Destination port | Mục đích |
| --- | --- | ---: | --- |
| `vm-fl-server-nsg` | Public IP máy cá nhân `/32` | TCP 22 | SSH tới server |
| Mỗi client NSG | `<SERVER_PRIVATE_IP>/32` hoặc subnet server | TCP 22 | SSH qua `ProxyJump` |
| `vm-fl-server-nsg` | `<EA_SUBNET_CIDR>` | TCP 8000 | Client 1–2 tới SuperLink |
| `vm-fl-server-nsg` | `<KC_SUBNET_CIDR>` | TCP 8000 | Client 3–5 qua peering |

Trong form rule, **Source = IP Addresses**, **Source IP addresses/CIDR ranges** là
CIDR tương ứng, **Source port ranges = `*`**, **Destination port ranges** là
`22` hoặc `8000`, **Protocol = TCP**, **Action = Allow**. Không dùng IP public
của client làm nguồn cho Flower: các node gọi **private IP server**. Không mở
TCP 8000 từ `Any/Internet` nếu chỉ có các client nội bộ.

## 4. Outbound internet để cài Python packages

Trên từng client, kiểm tra:

```bash
getent ahostsv4 pypi.org
curl -4 -I --max-time 20 https://pypi.org/simple/flwr/
curl -4 -I --max-time 20 https://www.microsoft.com
```

Nếu DNS phân giải được nhưng cả hai `curl` đều timeout ở TCP 443, mở
**VNet → Subnets → subnet của client** và kiểm tra **Private subnet / Default
outbound access**. Với subnet private, cấu hình outbound rõ ràng như **NAT
Gateway** gắn vào subnet. Trong lần demo trước, tắt tùy chọn private subnet
đã giúp cài package; đây là cách phụ thuộc default outbound, không phải cấu
hình outbound ổn định cho triển khai lâu dài. NAT Gateway có chi phí và public
IP riêng. NSG outbound cũng phải cho phép HTTPS. Sau thay đổi, thử lại `curl`
trước khi chạy `pip`.

## 5. SSH từ Windows vào 6 VM

Mở `C:\Users\ACER\.ssh\config` và điền IP/key thực tế. Ví dụ:

```sshconfig
Host vm-fl-server
    HostName <SERVER_PUBLIC_IP>
    User azureuser
    IdentityFile C:/Users/ACER/.ssh/<PRIVATE_KEY_FILE>
    ServerAliveInterval 30

Host vm-fl-client-1
    HostName <CLIENT_1_PRIVATE_IP>
    User azureuser
    IdentityFile C:/Users/ACER/.ssh/<PRIVATE_KEY_FILE>
    ProxyJump vm-fl-server

Host vm-fl-client-2
    HostName <CLIENT_2_PRIVATE_IP>
    User azureuser
    IdentityFile C:/Users/ACER/.ssh/<PRIVATE_KEY_FILE>
    ProxyJump vm-fl-server

# Lặp lại cho client-3, client-4, client-5 với private IP của từng máy.
```

Kiểm tra bằng PowerShell:

```powershell
ssh -o ConnectTimeout=15 vm-fl-server "hostname"
ssh -o ConnectTimeout=15 vm-fl-client-3 "hostname"
```

Nếu client timeout, thử server trước. Nếu server SSH bình thường nhưng client
timeout, kiểm tra private IP, peering, client NSG TCP 22 từ server, trạng thái
VM và SSH service. `ssh -v -o ConnectTimeout=10 vm-fl-client-3` chỉ rõ bước
đang kẹt. Timeout ngắt quãng tới server public IP từng tự hết; kiểm tra lại
trước khi kết luận VM thiếu CPU. CPU không đạt 100% không chứng minh SSH/network
ổn định. SCP có thể dùng `-o ConnectTimeout=15 -o ConnectionAttempts=3`.

## 6. Cài môi trường trên từng VM

Trên server và từng client, khi outbound đã thông:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip openssl curl
python3 --version
python3 -m venv ~/fl-venv
source ~/fl-venv/bin/activate
python -m pip install --upgrade pip
python -m pip install 'flwr==1.42.0'
flwr --version
mkdir -p ~/project-cloud/data/experiments/split_seed_42 ~/project-cloud/certs
```

Python phải **>=3.11,<4.0** theo `flower-app/pyproject.toml`; lần triển khai
đã dùng Python 3.12. Nếu `python3` thấp hơn 3.11, cài bản tương thích trước
khi tạo venv. Không dùng `sudo pip` để trộn package hệ thống và venv.

## 7. Tạo split IID trên máy Windows và chuyển đúng dữ liệu

Ở thư mục dự án `C:\Users\ACER\Documents\ChatGPT\Project Cloud`, đặt nguồn
`data\cs-training.csv`, mở `notebooks\federated_random_forest.ipynb`, chạy
tuần tự các cell tạo split/partition. Kiểm tra:

```powershell
$project = 'C:\Users\ACER\Documents\ChatGPT\Project Cloud'
$split = Join-Path $project 'data\experiments\split_seed_42'
Get-Item (Join-Path $split 'feature_schema.json'), (Join-Path $split 'split_metadata.json'), (Join-Path $split 'validation.csv'), (Join-Path $split 'test.csv')
Get-Content (Join-Path $split 'iid\clients_5\summary.json')
```

Kỳ vọng 90.000 hàng train chia `18001, 18000, 18000, 18000, 17999`, và
validation/test mỗi tập 30.000 hàng. Seed, schema, median fit trên **train**
và SHA-256 phải giống nhau ở các nơi. CSV được tách **trên máy Windows trước**, 
sau đó chỉ gửi mỗi client file của nó. Đây là mô phỏng 5 chi nhánh bằng 5 VM;
không phải 5 chi nhánh tự thu thập dữ liệu gốc.

Trên server, tạo thư mục:

```powershell
ssh vm-fl-server 'mkdir -p ~/project-cloud/data/experiments/split_seed_42/iid/clients_5 ~/project-cloud/results'
scp (Join-Path $split 'feature_schema.json') (Join-Path $split 'split_metadata.json') (Join-Path $split 'validation.csv') (Join-Path $split 'test.csv') `
  vm-fl-server:/home/azureuser/project-cloud/data/experiments/split_seed_42/
scp (Join-Path $split 'iid\clients_5\summary.json') `
  vm-fl-server:/home/azureuser/project-cloud/data/experiments/split_seed_42/iid/clients_5/
```

Trên mỗi client chỉ gửi `feature_schema.json` và `client_<id>.csv`:

```powershell
foreach ($id in 1..5) {
    $vm = "vm-fl-client-$id"
    ssh $vm 'mkdir -p ~/project-cloud/data/experiments/split_seed_42/iid/clients_5'
    if ($LASTEXITCODE -ne 0) { throw "Không tạo được thư mục trên $vm" }
    scp (Join-Path $split 'feature_schema.json') `
      "${vm}:/home/azureuser/project-cloud/data/experiments/split_seed_42/"
    if ($LASTEXITCODE -ne 0) { throw "Không gửi được schema tới $vm" }
    scp (Join-Path $split "iid\clients_5\client_$id.csv") `
      "${vm}:/home/azureuser/project-cloud/data/experiments/split_seed_42/iid/clients_5/"
    if ($LASTEXITCODE -ne 0) { throw "Không gửi được CSV tới $vm" }
}
```

Kiểm tra hash từng CSV bằng `Get-FileHash -Algorithm SHA256` trên Windows và
`sha256sum` trên VM; đối chiếu với `summary.json`. Server chỉ giữ validation,
test, schema, split metadata, summary; không cần 5 CSV client. Client không nhận test labels.

## 8. Chuyển Flower App lên server

```powershell
ssh vm-fl-server 'mkdir -p ~/project-cloud'
scp -r (Join-Path $project 'flower-app') vm-fl-server:/home/azureuser/project-cloud/
ssh vm-fl-server 'ls -l ~/project-cloud/flower-app/pyproject.toml'
```

Nếu server đã có app và chỉ cập nhật phần xuất mô hình/API:

```powershell
scp (Join-Path $project 'flower-app\fl_app\server_app.py') `
    (Join-Path $project 'flower-app\fl_app\model_artifact.py') `
    (Join-Path $project 'flower-app\fl_app\evaluation.py') `
    (Join-Path $project 'flower-app\fl_app\client_app.py') `
    (Join-Path $project 'flower-app\fl_app\api.py') `
    vm-fl-server:/home/azureuser/project-cloud/flower-app/fl_app/
scp (Join-Path $project 'flower-app\pyproject.toml') `
    vm-fl-server:/home/azureuser/project-cloud/flower-app/pyproject.toml
```

Trên server:

```bash
source ~/fl-venv/bin/activate
cd ~/project-cloud/flower-app
grep requires-python pyproject.toml
python -m pip install -e .
```

Lỗi cũ: `requires-python = ">=3.10"` làm dependency resolution thất bại vì
Flower 1.42.0 cần Python >=3.11. File hiện phải là `>=3.11,<4.0`. Cảnh báo
`Recommended property "license" missing` không làm run thất bại. Flower tự
đưa app tới SuperNode khi chạy; không cần SCP `api.py` lên 5 client.
Để đo đủ metric, chạy lại với `evaluation.py`, `client_app.py` mới và chuyển
`split_metadata.json` lên server trước khi bắt đầu.

## 9. Tạo CA, certificate và chép CA tới client

Trên **server**, lấy private IP thực tế trong Portal rồi chạy:

```bash
SERVER_PRIVATE_IP='<SERVER_PRIVATE_IP>'
test "$SERVER_PRIVATE_IP" != '10.x.x.x' || { echo 'Thay bằng private IP thật'; exit 1; }
mkdir -p ~/project-cloud/certs
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

SAN phải hiện private IP thật của server và `127.0.0.1`. CA `ca.crt` có thể
phân phối; **không chép `ca.key` hay `server.key`** sang client. Trên PowerShell:

```powershell
$ca = Join-Path $env:TEMP 'fl-ca.crt'
scp -o ConnectTimeout=15 -o ConnectionAttempts=3 `
  vm-fl-server:/home/azureuser/project-cloud/certs/ca.crt $ca
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $ca)) {
    throw 'Chưa tải được ca.crt từ server; dừng tại đây'
}
foreach ($id in 1..5) {
    $vm = "vm-fl-client-$id"
    ssh $vm 'mkdir -p ~/project-cloud/certs'
    if ($LASTEXITCODE -ne 0) { throw "Không kết nối được $vm" }
    scp $ca "${vm}:/home/azureuser/project-cloud/certs/ca.crt"
    if ($LASTEXITCODE -ne 0) { throw "Không chép được CA tới $vm" }
}
```

Lỗi `scp: stat local ... fl-ca.crt: No such file` xuất hiện khi lượt tải CA
từ server đã timeout nhưng vòng lặp vẫn chạy. Luôn kiểm tra `$LASTEXITCODE`
và `Test-Path` trước khi phân phối.

## 10. Khởi động SuperLink và 5 SuperNode

Trên **server**, cửa sổ SSH riêng, giữ tiến trình chạy:

```bash
source ~/fl-venv/bin/activate
cd ~/project-cloud
flower-superlink \
  --host 0.0.0.0 --port 8000 \
  --ssl-ca-certfile ~/project-cloud/certs/ca.crt \
  --ssl-certfile ~/project-cloud/certs/server.crt \
  --ssl-keyfile ~/project-cloud/certs/server.key
```

Trên **mỗi client**, dùng ID đúng của VM đó; ví dụ client 2. Dán các dòng
`export` **riêng rẽ**, rồi kiểm tra giá trị trước khi khởi động:

```bash
source ~/fl-venv/bin/activate
export CLIENT_ID=2
export PROJECT_DATA_ROOT=/home/azureuser/project-cloud/data
export SERVER_PRIVATE_IP='<SERVER_PRIVATE_IP>'
printf 'CLIENT_ID=<%s>\n' "$CLIENT_ID"
test "$CLIENT_ID" = '2' || { echo 'CLIENT_ID sai'; exit 1; }
test -f "$PROJECT_DATA_ROOT/experiments/split_seed_42/iid/clients_5/client_${CLIENT_ID}.csv"
test -f ~/project-cloud/certs/ca.crt
flower-supernode \
  --superlink "${SERVER_PRIVATE_IP}:8000" \
  --root-certificates ~/project-cloud/certs/ca.crt \
  --host 127.0.0.1 --port 9094
```

Đổi `CLIENT_ID=1..5` trên đúng VM. Vì mỗi client là VM riêng, chúng có thể
cùng dùng local port 9094. Nếu client không nối được, kiểm tra TCP:

```bash
timeout 5 bash -c "echo > /dev/tcp/${SERVER_PRIVATE_IP}/8000" && echo FLOWER_TCP_OK
```

Lỗi đã gặp: `invalid literal for int() with base 10: '2export'` nghĩa là
`CLIENT_ID` bị dính với lệnh `export` tiếp theo. Dừng SuperNode cũ bằng
`Ctrl+C`, đặt lại `export CLIENT_ID=2` trong **chính shell khởi động node**,
kiểm tra `printf`, rồi khởi động lại; sửa biến trong shell khác không thay đổi
environment của tiến trình đang chạy.

## 11. Cấu hình Flower CLI và chạy thí nghiệm IID

Trên server, trong `~/.flwr/config.toml` thêm profile (giữ các profile khác
nếu đã có):

```toml
[superlink.azure-private]
address = "127.0.0.1:8000"
root-certificates = "/home/azureuser/project-cloud/certs/ca.crt"
```

Kiểm tra `flwr ls azure-private`. Sau khi cả 5 SuperNode đã kết nối, mở
**terminal SSH khác trên server**:

```bash
source ~/fl-venv/bin/activate
cd ~/project-cloud/flower-app
export PROJECT_DATA_ROOT=/home/azureuser/project-cloud/data
export PROJECT_RESULTS_ROOT=/home/azureuser/project-cloud/results
mkdir -p "$PROJECT_RESULTS_ROOT"
flwr run . azure-private --stream 2>&1 | tee "$PROJECT_RESULTS_ROOT/flower_console_iid.log"
```

`pyproject.toml` hiện đặt `mode=iid`, `num-clients=5`, `trees-per-client=20`,
`seed=42`. Kiểm tra output có `total_trees: 100`, `test_rows: 30000`, đủ 5
client và **không có** `ERROR : Exit Code: 201`. Chỉ `echo "$?"` sau
`... | tee` từng hiện `0` dù ServerApp lỗi; xác nhận bằng log, trạng thái run
và JSON kết quả thực tế:

```bash
flwr ls azure-private
ls -lh "$PROJECT_RESULTS_ROOT/flower_seed42_iid_clients5.json"
python -m json.tool "$PROJECT_RESULTS_ROOT/flower_seed42_iid_clients5.json" | head -40
```

Lỗi `Expected 5 successful replies, got 5` trước đây nghĩa là có đủ 5 reply
nhưng một reply chứa lỗi. Bản `server_app.py` hiện in `Client replies failed`
kèm `node`, `code`, `reason`. `node` là ID Flower, không nhất thiết là
`CLIENT_ID`. Xem `reason` và log terminal SuperNode để sửa đúng máy.

Kết quả IID Azure đã quan sát trước khi thêm export: ROC-AUC ~`0.866876`, AP
~`0.407101`, F1 ~`0.443339`. Đây là mốc kiểm tra gần đúng, **không phải giá
trị bắt buộc** sau khi cài lại package. `numeric_payload_bytes` chỉ là tổng
byte mảng cây, không phải tổng byte gRPC/TLS/VM network.

## 12. Xuất mô hình sau run và kiểm tra artifact

Mã mới trong `fl_app/model_artifact.py` và `server_app.py` lưu:

```text
~/project-cloud/results/
  flower_seed42_iid_clients5.json
  models/run_<FLOWER_RUN_ID>/
    model.json
    forest.npz
```

`model.json` ghi thứ tự 10 features, median lấy từ train, threshold chọn trên
validation, run ID, số cây và checksum. `forest.npz` chứa cây dạng mảng số,
không dùng pickle khi nạp. Run IID cũ trước khi cập nhật mã **không có** hai
file này; không thể dựng lại rừng cây chỉ từ JSON metrics. Chạy lại bước 11
sau khi cập nhật code ở bước 8.

```bash
python - <<'PY'
import json
from pathlib import Path
p = Path('/home/azureuser/project-cloud/results/flower_seed42_iid_clients5.json')
r = json.loads(p.read_text())
model = Path(r['model_artifact'])
print('Model manifest:', model, model.exists())
print('Forest arrays:', model.with_name('forest.npz'), model.with_name('forest.npz').exists())
print('Trees:', r['total_trees'], 'Test rows:', r['test_rows'])
PY
```

Giữ model và log theo `run_id` để tránh nhầm kết quả giữa các lần chạy. Chỉ
server có artifact tổng hợp; client không cần nhận model triển khai web.

## 13. Chạy API để web gọi dự đoán

Luồng hiện dùng là publish model lên Blob và API tự nạp `latest-iid.json` qua Managed Identity. Xem [model-artifacts.md](model-artifacts.md) để cấu hình. Các lệnh `MODEL_DIR` bên dưới chỉ dùng để thử một model cố định khi chưa bật Blob artifact.

Trên server, lấy `MODEL_DIR` từ JSON kết quả thay vì gõ run ID cũ:

```bash
source ~/fl-venv/bin/activate
cd ~/project-cloud/flower-app
export MODEL_DIR="$(python - <<'PY'
import json
from pathlib import Path
p = Path('/home/azureuser/project-cloud/results/flower_seed42_iid_clients5.json')
print(Path(json.loads(p.read_text())['model_artifact']).parent)
PY
)"
echo "$MODEL_DIR"
uvicorn fl_app.api:app --host 127.0.0.1 --port 8080
```

Ở terminal SSH khác trên server:

```bash
curl http://127.0.0.1:8080/healthz
curl -X POST http://127.0.0.1:8080/predict \
  -H 'Content-Type: application/json' \
  -d '{"features":{"RevolvingUtilizationOfUnsecuredLines":0.15,"age":52,"NumberOfTime30-59DaysPastDueNotWorse":0,"DebtRatio":0.37,"MonthlyIncome":5400,"NumberOfOpenCreditLinesAndLoans":8,"NumberOfTimes90DaysLate":0,"NumberRealEstateLoansOrLines":1,"NumberOfTime60-89DaysPastDueNotWorse":0,"NumberOfDependents":0}}'
```

`/predict` trả `risk_probability`, `predicted_label`, `threshold`,
`imputed_features`, `model_run_id`, `mode`. Feature thiếu hoặc `null` được điền
bằng train median; tên feature lạ bị từ chối. Web gửi JSON có cùng 10 tên
feature và hiển thị xác suất, nhãn, phiên bản model. Cho demo, web và API
đi qua cùng HTTPS reverse proxy; Uvicorn vẫn chỉ bind `127.0.0.1`. Chưa mở
NSG 8080 ra Internet. Thêm xác thực và log request trước khi cho người ngoài
gửi dữ liệu. Đây là xác suất rủi ro theo mô hình học thuật, không phải quyết
định tín dụng tự động.

## 14. Đối chiếu centralized, giám sát và lưu bằng chứng

Đối chiếu với `results/protocol_v1/seed42_iid_clients5_trees20/test_metrics.csv`
trên máy Windows: cùng source/split/test, 100 cây, 10 feature, median train,
RF `max_depth=10`, `min_samples_leaf=5`, `max_features=sqrt`, `class_weight=None`.
Ngưỡng F1 của mỗi mô hình được chọn trên validation rồi đánh giá test.
Ghi ROC-AUC, AP, F1, precision, recall, confusion matrix và threshold; đừng
kết luận ưu thế thống kê chỉ từ một run.

Trên **Azure Portal → Monitor → Workbooks**, gom chart `Percentage CPU`,
`Network In/Out Total`, `Disk Read/Write Bytes` của 3 VM East Asia và 3 VM
Korea Central thành hai nhóm cùng thời điểm UTC. Dùng Log Analytics + Azure
Monitor Agent nếu cần guest RAM/log. Với **Network Watcher → Connection
Monitor**, đo TCP tới server private IP:8000 từ từng client, lưu p50/p95 và
phân nhóm region. Ghi thời gian bắt đầu/kết thúc run và kích thước CSV, JSON,
model. VM network totals gồm cả SSH và traffic khác, không được gọi là payload
Flower chính xác. Azure Monitor không tự tính model metrics; giữ JSON riêng.
Run IID đã dùng Blob cho partition và validation/test; JSON có thời gian tải
Blob theo client và server. Xem [blob-data.md](blob-data.md) để đối chiếu với
Azure Storage metrics theo cùng khoảng UTC; thời gian ứng dụng không thay thế
Storage service latency.
Xem Cost Management/Quotas để ghi chi phí và vCPU theo region. Nếu đo API,
thu request count, lỗi, p50/p95 latency sau khi API chạy.

Từ Windows, tải artifact và log về một thư mục riêng:

```powershell
$evidence = Join-Path $project 'results\azure_iid_run'
New-Item -ItemType Directory -Force -Path $evidence | Out-Null
scp vm-fl-server:/home/azureuser/project-cloud/results/flower_seed42_iid_clients5.json $evidence
scp vm-fl-server:/home/azureuser/project-cloud/results/flower_console_iid.log $evidence
# Đọc model_artifact trong JSON để biết run ID, rồi chép đúng thư mục:
scp -r vm-fl-server:/home/azureuser/project-cloud/results/models/run_<FLOWER_RUN_ID> $evidence
```

Lưu cùng ảnh/chỉ số Monitor, topology, SKU, CIDR, run ID, UTC interval,
SHA-256 và phiên bản package. Không đưa khóa, SAS hoặc raw CSV lên repo/web.

## 15. Các lỗi đã gặp và cách xử lý nhanh

| Triệu chứng | Nguyên nhân/cách xử lý |
| --- | --- |
| Không tạo thêm VM dù Basv2 `6/10` | Xem **Total Regional vCPUs**; lần trước tổng region `6/6`. Chọn region khác hoặc SKU/vCPU phù hợp, hoặc xin tăng quota nếu subscription cho phép. |
| Không chọn được VNet East Asia cho VM Korea Central | Tạo VNet tại Korea Central, CIDR không trùng, peer hai VNet. |
| `curl pypi.org` và `microsoft.com` cùng timeout, DNS vẫn có IP | Kiểm tra private subnet/outbound; gắn NAT Gateway hoặc cấu hình outbound phù hợp; kiểm tra NSG outbound. |
| SSH client timeout, server SSH được | Kiểm tra ProxyJump, private IP, NSG client TCP 22 từ server, peering, VM. Thử `ssh -v` và `ConnectTimeout`. |
| SCP timeout một lần rồi chạy lại được | Xác minh SSH server, chạy SCP với `ConnectionAttempts=3`, kiểm tra file trên đích. |
| `scp: stat local ... fl-ca.crt` | Tải CA từ server đã thất bại; kiểm tra `$LASTEXITCODE` và `Test-Path` rồi mới copy sang client. |
| `scp: stat local ./flower-app/...` từ `C:\Users\ACER` | Dùng `$project` hoặc đường dẫn đầy đủ; thư mục hiện tại không phải project. |
| Flower dependency resolution lỗi | `requires-python` phải `>=3.11,<4.0`; kiểm tra `python --version`, upload pyproject mới rồi `pip install -e .`. |
| `Expected 5 successful replies, got 5` | Có reply mang lỗi; dùng server_app mới để đọc `Client replies failed` và log SuperNode. |
| `CLIENT_ID='2export'` | Hai lệnh `export` dính nhau; restart SuperNode sau khi `export CLIENT_ID=2` và kiểm tra bằng `printf`. |
| `Exit code: 0` nhưng log có `Exit Code: 201` | Không dùng exit code của pipeline/CLI làm bằng chứng; xem Flower run status, log và JSON artifact. |
| JSON metrics có nhưng không có `model.json` | Đó là run trước khi thêm export; upload code mới và chạy lại. |

## Nguồn kỹ thuật

- [Microsoft: quản lý VNet peering](https://learn.microsoft.com/en-us/azure/virtual-network/virtual-network-manage-peering)
- [Microsoft: default outbound/private subnet](https://learn.microsoft.com/en-us/azure/virtual-network/ip-services/default-outbound-access)
- [Microsoft: quota vCPU theo region](https://learn.microsoft.com/en-us/azure/quotas/regional-quota-requests)
- [Flower: TLS cho SuperLink, SuperNode và CLI](https://flower.ai/docs/framework/how-to-enable-tls-connections.html)
- [Flower: cấu hình profile kết nối](https://flower.ai/docs/framework/main/en/ref-flower-configuration.html)

## 16. Phương án triển khai web và API cho bản demo

### 16.1 Kiến trúc được chọn

```text
Trình duyệt
   │ HTTPS 443
   ▼
Public IP hiện có → NSG server → Nginx trên vm-fl-server
                                  ├── /              → HTML/CSS/JavaScript tĩnh
                                  ├── /api/predict   → FastAPI 127.0.0.1:8080/predict
                                  └── /api/healthz   → FastAPI 127.0.0.1:8080/healthz
                                  └── /api/dashboard → FastAPI 127.0.0.1:8080/dashboard
                                                       │
                                                       ▼
                                 results/models/run_<RUN_ID>/{model.json,forest.npz}

Azure Monitor/Workbook ← metrics của 6 VM, latency và log có cấu hình thu thập
```

Đặt web và API trên **VM server hiện có**, không tạo VM thứ bảy. Nginx phục vụ
giao diện và chuyển `/api/*` tới Uvicorn ở loopback; trình duyệt chỉ thấy một
origin HTTPS nên không cần mở CORS rộng. `forest.npz`, CSV test/validation và
log nội bộ nằm ngoài web root. Mã giao diện và cấu hình mẫu Nginx/systemd đã
có trong repo; việc cài và chạy trên Azure vẫn cần thực hiện.

| Tài nguyên | Trạng thái | Công dụng và cấu hình đề xuất |
| --- | --- | --- |
| `vm-fl-server` East Asia | Đã có | Giữ Flower SuperLink, model artifact, FastAPI, Nginx. Sau huấn luyện, API đọc model một lần; thử tải trước khi quyết định tăng SKU. |
| Public IP + NIC server | Đã có | Điểm truy cập SSH và HTTPS. Giữ SSH 22 chỉ từ IP quản trị. |
| NSG server | Đã có, cần bổ sung | Giữ Flower TCP 8000 chỉ từ CIDR client; mở TCP 443 cho người xem demo; không mở 8080. TCP 80 chỉ dùng nếu quy trình cấp/chuyển hướng chứng chỉ cần. |
| 5 client VM + peering | Đã có | Chỉ phục vụ huấn luyện và thí nghiệm; không nhận request dự đoán từ web. Có thể deallocate sau khi lưu đủ bằng chứng nếu không chạy lại FL. |
| `forest.npz` + `model.json` | Chưa xác nhận trên Azure | Tạo khi chạy lại FL với mã export mới. Lưu theo `run_id`, kiểm tra checksum, giữ bản được chọn để phục vụ. |
| Nginx + systemd unit Uvicorn | Cần thêm trên server | Nginx phục vụ static assets và proxy; systemd tự khởi động lại API sau reboot. Chạy một Uvicorn worker trước, đo RAM/latency. |
| DNS + chứng chỉ HTTPS | Cần quyết định | Dùng subdomain do nhóm/trường sở hữu và chứng chỉ hợp lệ để demo công khai. Nếu chưa có tên miền, thử nội bộ qua SSH tunnel trước; cert Flower hiện tại chỉ dùng cho Flower, không coi là cert web công khai. |
| Azure Monitor Workbook | Theo phần 14 | Gom hai region, CPU, network, disk, latency; chụp theo UTC interval của run. |
| Log Analytics + Azure Monitor Agent | Tùy chọn có chi phí | Chỉ bật khi cần guest RAM và log tập trung; đặt retention/thu thập theo nhu cầu rubric. |
| Blob Storage | Tùy chọn theo rubric | Chỉ tạo nếu triển khai thật bài đo Blob I/O; SCP hiện tại không chứng minh tiêu chí Blob. |

**Lý do chọn VM hiện có:** giảm tài nguyên mới và giữ model cạnh API. Đây là
phương án demo có giới hạn sẵn sàng: nếu server VM dừng thì web/API cũng dừng;
huấn luyện đồng thời có thể cạnh tranh CPU/RAM với inference, vì vậy đo tải và
ưu tiên trình diễn sau khi train xong. Không đưa ra chi phí cố định khi chưa có
SKU, thời lượng chạy, region và lượng log thực tế; xem Cost Analysis/Budgets.

**Phương án khác:** Azure Static Web Apps Free host giao diện tĩnh và có TLS,
nhưng khả năng *Bring your own API* tích hợp chỉ có ở Standard và danh sách
backend hỗ trợ không gồm VM trực tiếp. Nếu chọn Free, trình duyệt vẫn cần gọi
API VM qua một public HTTPS endpoint riêng, phát sinh CORS, xác thực và quản
lý hai origin. Vì vậy chưa chọn cho bản demo này.

### 16.2 Các bước triển khai ứng dụng sau khi có model

1. **Chốt artifact:** hoàn thành bước 12; đọc `model_artifact` từ JSON kết quả,
   kiểm tra `forest.npz`, `model.json` và gọi API ở loopback theo bước 13.
2. **Giữ API chạy:** tạo systemd service với `WorkingDirectory` là
   `/home/azureuser/project-cloud/flower-app`, `MODEL_DIR` là thư mục model
   được chọn, `ExecStart` dùng `/home/azureuser/fl-venv/bin/uvicorn
   fl_app.api:app --host 127.0.0.1 --port 8080`. Dùng đường dẫn tuyệt đối
   trong unit; đặt user
   `azureuser`. Kiểm tra `systemctl status`, `journalctl` và `/healthz` sau
   reboot. Khi đổi model, cập nhật `MODEL_DIR` và restart service có kiểm tra.
3. **Dựng giao diện tĩnh:** tạo web form cho đúng 10 feature của
   `feature_schema.json`. Nginx serve file build ở thư mục riêng, ví dụ
   `/var/www/fl-credit/`; chỉ public các metrics JSON đã lọc dữ liệu cần trình
   bày. Không đưa `data/`, `certs/`, `results/models/` vào web root.
4. **Reverse proxy:** cấu hình Nginx chuyển `/api/predict` sang
   `http://127.0.0.1:8080/predict` và `/api/healthz` sang `/healthz`; giữ
   phương thức POST, `Content-Type: application/json`, giới hạn request body
   và timeout. Frontend gọi đường dẫn tương đối `/api/predict`.
5. **HTTPS và truy cập:** gắn DNS/subdomain vào public IP server; cấp TLS cert
   cho Nginx, mở NSG TCP 443. Kiểm tra từ máy Windows bằng trình duyệt và
   `curl`. Giới hạn demo bằng xác thực ở proxy hoặc ứng dụng; thêm rate limit.
   Không log số liệu tài chính người dùng trong access log; chỉ lưu request ID,
   status, elapsed time và model version. Nếu chưa có domain/cert, demo nội
   bộ bằng SSH tunnel thay vì public endpoint HTTP không mã hóa.
6. **Giám sát và chứng cứ:** ghi UTC start/end, model run ID, 20–50 request
   thử với dữ liệu giả, số success/error, p50/p95 latency, CPU/RAM server.
   Lưu ảnh màn hình web, JSON trả về, log đã loại dữ liệu nhạy cảm và biểu đồ
   Azure Monitor. Kiểm tra cost trước/sau giai đoạn demo.

### 16.3 Hợp đồng API và dữ liệu hiển thị

API **đã có** `GET /healthz`, `GET /dashboard` và `POST /predict` trong `fl_app/api.py`.
Request `POST /predict` chứa object `features` với tên đặc trưng đúng schema.
Response gồm `risk_probability`, `predicted_label`, `threshold`,
`imputed_features`, `model_run_id`, `mode`. Frontend cần hiện `mode` và
`model_run_id` cạnh kết quả để truy vết; giải thích `predicted_label` là kết
quả theo ngưỡng validation, không phải quyết định cấp tín dụng. Nút “Thử dữ
liệu mẫu” phải dùng dữ liệu giả, không điền một hồ sơ thật mặc định.

Trang So sánh đọc `/api/dashboard`, endpoint lọc metric từ JSON FL và hàng
`centralized,best_f1` của CSV; không xuất raw CSV ra web. API hiện chưa có
endpoint `/runs`, `/metrics` hoặc lưu lịch sử người dùng. Không gửi model
artifact hoặc private IP vào tài nguyên web tĩnh. Lệnh build, copy và bật
service: xem [web-api.md](web-api.md).

## 17. Danh sách frame cần thiết cho web và rubric

`Frame` ở đây là **màn hình giao diện**; Azure Monitor Workbook là màn hình
giám sát riêng trong Azure. Đã kiểm tra trực tiếp sheet **Bài tập Lớn** của
`C:\Users\ACER\Downloads\Rubik Đánh giá bài tập quá trình & Bài tập Lớn.xlsx`.
Hàng 24 nói phần này chọn **một trong ba hướng**: Web, Trực quan dữ liệu, hoặc
Phân tích dữ liệu. Dự án Federated Random Forest theo hướng **Phân tích dữ
liệu**, nên các hàng **34–37** là phần trực tiếp cần chứng minh:

| Hàng rubric gốc | Điểm | Yêu cầu | Bằng chứng của dự án |
| --- | ---: | --- | --- |
| 34 | 1,0 | Huấn luyện model trên tập dữ liệu | Notebook centralized, 5 SuperNode và Flower run thành công; split/seed, log và model artifact. |
| 35 | 0,5 | API cho phép sử dụng model | FastAPI `/predict` chạy trên Azure, request/response thực. |
| 36 | 1,0 | Trực quan kết quả trên tham số hoặc loại model | Bảng/biểu đồ Centralized vs FL-IID; thêm FL non-IID khi có run thật; confusion matrix và ngưỡng. |
| 37 | 0,5 | Web gửi request tới API cloud, nhận và parse kết quả | Form dự đoán F2 chạy trên Azure, hiển thị response, xử lý lỗi. |

Hàng **25–28** (ít nhất 4 trang web, blue/green, 2 service, FaaS) thuộc
hướng **Web**; hàng **29–33** (4 report trên SaaS, realtime, chia sẻ theo
quyền, mobile responsive) thuộc hướng **Trực quan dữ liệu**. Chúng không nên
được trình bày như yêu cầu bắt buộc đồng thời của hướng Phân tích dữ liệu.
Một website responsive và các frame bổ sung vẫn giúp demo, nhưng không phải
căn cứ để tự nhận điểm của hai hướng còn lại.

**Ba frame lõi cần triển khai cho hàng 34–37 là F1–F3.** F4–F6 là màn hình
bổ trợ cho các tiêu chí hạ tầng, dữ liệu và báo cáo ở những mục khác của rubric;
có thể đưa chúng vào báo cáo/Workbook thay vì xây thành trang web riêng.

| Frame | Nội dung và tương tác | Nguồn dữ liệu | Liên hệ rubric |
| --- | --- | --- | --- |
| **F1 – Tổng quan** | Tên đề tài, trạng thái model/API, run ID, 1 server + 5 client, hai region, 100 cây; thẻ ROC-AUC/AP/F1 của run được chọn; nút “Dự đoán” và “Xem so sánh”. | JSON kết quả FL + `/healthz` | Giải thích mô hình đã huấn luyện (hàng 34), điều hướng demo. |
| **F2 – Dự đoán rủi ro** | Form 10 đặc trưng với nhãn, đơn vị/giải thích ngắn; kiểm tra số hợp lệ, biểu thị trường điền median; nút gửi và trạng thái loading/error. Kết quả hiện xác suất, ngưỡng, nhãn, phiên bản model; không hiển thị “duyệt/từ chối vay”. | `POST /api/predict` | API/web và inference thực (hàng 35, 37). |
| **F3 – So sánh mô hình** | Bảng và biểu đồ Centralized vs FL-IID; thêm FL non-IID khi có run thật. Cùng hàng cho ROC-AUC, AP, F1, precision, recall, threshold, confusion matrix, 100 cây, train/test size. Có ghi rõ central dùng toàn bộ train còn IID là cách chia cho client. | Centralized CSV/JSON + FL JSON đã kiểm chứng | Chất lượng model, trực quan và phép so sánh công bằng (hàng 34–36). |
| **F4 – Thí nghiệm & topology (bổ trợ)** | Sơ đồ server East Asia, client 1–2 East Asia, client 3–5 Korea Central; seed, split 60/20/20, cây/client, từng client row count, SHA check, thời gian run. Phần network tách payload NumPy khỏi network bytes. | Manifest split, Flower JSON, log đo đạc | Kiến trúc cloud, ETL/split, cross-region latency, thời gian và tài nguyên (hàng 6–7, 19, 21). |
| **F5 – Giám sát & chi phí (bổ trợ)** | Liên kết Workbook/ảnh có timestamp; CPU/RAM/network/disk, p50/p95 TCP latency theo region, API request count/error/p50/p95, Cost Analysis và quota. Chỉ hiện số đã đo; gắn thời gian và nguồn cho mỗi chart. | Azure Monitor, Connection Monitor, API log, Cost Analysis | Vận hành, region và chi phí (hàng 6–7, 21, 44). |
| **F6 – Dữ liệu & bằng chứng (bổ trợ)** | Nguồn dữ liệu, số hàng, split/hash, train-only median, client partitions, danh sách artifact và link tải báo cáo đã lọc. Thêm bảng Blob upload/download throughput/latency **chỉ khi đã thực hiện phép đo Blob thật**. | Split metadata, summary, log, Blob metrics nếu có | Data/ETL, Blob I/O và tính tái lập (hàng 18–19, 22). |

**Ưu tiên xây dựng:** F1–F3 với F2 dự đoán thật là lõi demo; F4–F6 phục vụ
minh chứng và có thể trình bày bằng báo cáo/Workbook. Không cần
thêm frame đăng nhập hay quản trị phức tạp nếu proxy chỉ mở cho nhóm chấm;
nếu demo công khai thì bổ sung bước xác thực ở 16.2.

### 17.1 Wireframe chữ cho ba frame lõi

```text
F1 TỔNG QUAN
[Logo/Đề tài] [Tổng quan] [Dự đoán] [So sánh] [Thí nghiệm] [Giám sát]
[Model online?] [Run ID] [IID / 5 client / 100 cây]
[ROC-AUC] [Average Precision] [F1]
[Sơ đồ 2 region + 6 VM]           [Chạy thử dự đoán →]
[Nguồn dữ liệu | seed | thời điểm run | giới hạn phép đo]

F2 DỰ ĐOÁN
[10 trường feature theo schema; chỉ rõ đơn vị và trường có thể bỏ trống]
[Dữ liệu mẫu] [Xóa] [Dự đoán]
[Trạng thái API / lỗi validation]
[Xác suất rủi ro] [Ngưỡng] [Nhãn 0/1]
[Trường được điền median] [Model run ID] [Giải thích phạm vi học thuật]

F3 SO SÁNH
[Chọn run FL-IID] [Chọn run FL-non-IID nếu có]
[Centralized | FL-IID | FL-non-IID: AP, AUC, F1, precision, recall]
[Biểu đồ metric] [Hai confusion matrix] [Threshold từng mô hình]
[Cùng split/test/seed; 100 cây; khác cách phân bổ train]
```

### 17.2 Tiêu chí nghiệm thu web

1. `/healthz` sẵn sàng và hiển thị đúng `model_run_id`; một request mẫu qua
   trình duyệt trả kết quả giống gọi API trực tiếp với cùng JSON input.
2. Không có file `forest.npz`, raw CSV, private key hoặc thông tin riêng của
   client truy cập được qua URL web.
3. F3 dùng **cùng test 30.000 hàng** và nêu rõ central vs FL-IID; non-IID chỉ
   hiện sau khi run và lưu artifact thật. Có nhãn threshold từng mô hình.
4. F4–F6 có nguồn, UTC interval và run ID cho số liệu; không trình bày
   `numeric_payload_bytes` như tổng traffic mạng, không trình bày SCP là Blob.
5. Có bằng chứng HTTPS/auth, API success/error/latency, Azure Monitor của hai
   region, chi phí/quota và ảnh demo để nộp cùng báo cáo.

### 17.3 Việc còn phải làm để frame có dữ liệu thật

| Việc | Lý do | Đầu ra kiểm chứng |
| --- | --- | --- |
| Chạy lại FL với mã export | Đã có run IID `6558643287244268762`, model và metrics trên Blob | Run kế tiếp xác nhận tự publish `latest-iid.json` |
| Triển khai frontend và Nginx/systemd | Preview Azure đã hoạt động qua SSH tunnel; chưa công khai HTTPS | Domain, TLS, ảnh F1–F3 và request dự đoán thật qua HTTPS |
| Đo và ghi API latency/error | API hiện chưa gửi custom metrics vào Azure Monitor | Log hoặc dashboard có request count, error rate, p50/p95 |
| Chạy non-IID trên cùng holdout | Hiện mới có kết quả Azure IID được xác nhận | JSON FL non-IID và hàng so sánh F3 |
| Tự động hóa ETL nếu rubric yêu cầu | Notebook chia file thủ công chưa chứng minh ETL tự động | Log pipeline, số hàng, SHA, trạng thái theo run ID |
| Thực hiện benchmark Blob nếu rubric yêu cầu | Đã có download timings trong JSON; cần số Azure Storage Metrics cùng UTC | Upload/download timings và Blob Metrics thật |
| Chốt giám sát và chi phí | Screenshot trống không phải bằng chứng phép đo | Workbook, latency hai region, Cost Analysis theo UTC interval |

**Nguồn rubric đã xác minh:** sheet `Bài tập Lớn` trong file Excel ở đường dẫn
ghi trên. Bảng đối chiếu cũ tại `deployment/azure/monitoring.md` vẫn hữu ích
cho việc đo đạc, nhưng không dùng nó để gộp ba hướng ở hàng 24 thành một bộ
yêu cầu bắt buộc. Dữ liệu `data/cs-training.csv` hiện khoảng **7,56 MB**;
rubric hàng 6 có thang kích thước KB/MB/GB, nên cần báo kích thước thực và
không tự nhận mức dữ liệu GB hoặc `>4GB`.

### Nguồn cập nhật cho phương án web

- [Microsoft: các gói Azure Static Web Apps](https://learn.microsoft.com/en-us/azure/static-web-apps/plans)
- [Microsoft: phạm vi API của Static Web Apps](https://learn.microsoft.com/en-us/azure/static-web-apps/apis-overview)
- [Microsoft: chi phí Log Analytics](https://learn.microsoft.com/en-us/azure/azure-monitor/logs/cost-logs)
