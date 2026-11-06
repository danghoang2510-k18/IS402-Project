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
Get-Item (Join-Path $split 'feature_schema.json'), (Join-Path $split 'validation.csv'), (Join-Path $split 'test.csv')
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
scp (Join-Path $split 'feature_schema.json') (Join-Path $split 'validation.csv') (Join-Path $split 'test.csv') `
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
test, schema, summary; không cần 5 CSV client. Client không nhận test labels.

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
Nếu rubric cần Blob I/O, phải thật sự dùng Blob và đo ingress/egress/latency
trong Storage Account; lần triển khai này dùng SCP nên chưa có bằng chứng Blob.
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
