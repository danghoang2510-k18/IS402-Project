# Đo chi phí truyền thông của vòng Flower

## Phạm vi phép đo

Ứng dụng hiện có **một vòng**: ServerApp gọi `grid.send_and_receive` một lần để gửi yêu cầu huấn luyện tới 5 SuperNode rồi nhận 5 rừng cây. JSON kết quả mới ghi `flower_round_started_utc` và `flower_round_finished_utc` ngay quanh lời gọi đó. Chỉ các gói **TCP/8000 giữa private IP server và 5 private IP client trong khoảng thời gian này** được tính là lưu lượng Flower của vòng. Server và client ở East Asia/Korea Central vẫn được tách theo ID.

Ba đại lượng phải ghi riêng:

| Đại lượng | Ý nghĩa |
| --- | --- |
| `numeric_tree_array_bytes` | Tổng `ndarray.nbytes` của các cây client gửi; không chứa Flower, gRPC, TLS, IP/TCP hoặc retransmission. |
| `tcp_payload_bytes` | Byte payload TCP bắt được trên NIC server; gồm TLS ciphertext/Flower, có thể gồm retransmission. Tính hai chiều. |
| `ip_bytes` | Tổng chiều dài gói IPv4 trên NIC server; gồm IP/TCP/TLS/Flower và retransmission, không gồm Ethernet FCS/chi phí hóa đơn Azure. Đây là số dùng làm **communication cost đo thực**. |

Blob download chạy qua HTTPS 443 và **không nằm trong** phép đo TCP/8000; báo riêng `clients[*].blob_download_seconds/data_bytes`. Azure Monitor `Network In/Out` dùng để đối chiếu quy mô tổng traffic VM, không thay số packet theo client và round. Không so sánh `numeric_tree_array_bytes` với `ip_bytes` như tỷ lệ overhead thuần vì chúng khác chiều, khoảng tính và nội dung.

## 1. Cập nhật ServerApp

Chép `flower-app/fl_app/server_app.py` mới cùng toàn bộ app lên `vm-fl-server`, cài lại `pip install -e .`. Shell chạy SuperLink và shell chạy `flwr run` phải source `~/project-cloud/flower_server_env.sh`. Chạy **run mới**; JSON của run cũ không có hai mốc UTC nên script phân tích sẽ từ chối. Giữ nguyên `mode=iid`, 5 client, 20 cây/client và split seed 42 để so sánh với baseline.

## 2. Bắt gói tại NIC server

Trong Portal lấy private IP thật của server và client 1–5. Trên server tìm interface đi đến client (ví dụ `eth0`):

```bash
ip route get <CLIENT_1_PRIVATE_IP>
sudo apt-get update
sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y tcpdump tshark
mkdir -p ~/project-cloud/results/traffic
```

Mở terminal SSH riêng **trước khi chạy `flwr run`**, thay các IP và interface thật. Tránh `-i any` nếu nó làm cùng một packet xuất hiện nhiều lần; chỉ bắt trên NIC của server. `-s 128` giữ header, không giữ toàn bộ payload. Capture vẫn là bằng chứng nội bộ vì có IP và mảnh TLS ciphertext.

```bash
sudo tcpdump -i eth0 -nn -s 128 \
  -w /home/azureuser/project-cloud/results/traffic/flower_tcp8000.pcap \
  'tcp port 8000 and (host <CLIENT_1_PRIVATE_IP> or host <CLIENT_2_PRIVATE_IP> or host <CLIENT_3_PRIVATE_IP> or host <CLIENT_4_PRIVATE_IP> or host <CLIENT_5_PRIVATE_IP>)'
```

Giữ terminal capture chạy, kiểm tra cả 5 SuperNode đã kết nối, sau đó chạy `flwr run . azure-private --stream` ở terminal khác như README. Khi run đã trả JSON thành công, nhấn `Ctrl+C` ở terminal capture. **Không chép PCAP vào báo cáo hoặc web.**

## 3. Xuất kích thước gói và tính theo round

Trên server, xuất CSV chỉ gồm timestamp/IP/độ dài, không gồm payload:

```bash
sudo tshark -r ~/project-cloud/results/traffic/flower_tcp8000.pcap \
  -Y 'tcp.port == 8000 && ip' -T fields \
  -E header=y -E separator=, -E quote=d \
  -e frame.time_epoch -e ip.src -e ip.dst -e ip.len -e tcp.len \
  > ~/project-cloud/results/traffic/flower_packet_lengths.csv
head -2 ~/project-cloud/results/traffic/flower_packet_lengths.csv
```

Trên Windows, tải CSV và JSON của **chính run đó** vào thư mục bằng chứng. Ví dụ PowerShell:

```powershell
$project = 'C:\Users\ACER\Documents\ChatGPT\Project Cloud'
Set-Location $project
$evidence = Join-Path $project 'results\azure_traffic_new_run'
New-Item -ItemType Directory -Path $evidence -Force | Out-Null
scp vm-fl-server:/home/azureuser/project-cloud/results/traffic/flower_packet_lengths.csv $evidence
scp vm-fl-server:/home/azureuser/project-cloud/results/flower_seed42_iid_clients5.json $evidence
python scripts/analyze_fl_traffic.py `
  --result (Join-Path $evidence 'flower_seed42_iid_clients5.json') `
  --packet-csv (Join-Path $evidence 'flower_packet_lengths.csv') `
  --server-ip <SERVER_PRIVATE_IP> `
  --client-ip 1=<CLIENT_1_PRIVATE_IP> `
  --client-ip 2=<CLIENT_2_PRIVATE_IP> `
  --client-ip 3=<CLIENT_3_PRIVATE_IP> `
  --client-ip 4=<CLIENT_4_PRIVATE_IP> `
  --client-ip 5=<CLIENT_5_PRIVATE_IP> `
  --output (Join-Path $evidence 'flower_traffic_round1.json')
```

Output có byte/gói **client→server** và **server→client** cho từng client, tổng IP bytes, TCP payload bytes, tốc độ MiB/s, mốc UTC, `run_id`, SHA của dữ liệu và các metric mô hình từ cùng Flower JSON. Script từ chối thiếu client, IP trùng, gói không thuộc 5 client hoặc một client có 0 traffic. Kiểm tra `run_id`, UTC window, số gói bỏ qua trước/sau round và tổng của 5 client. Đối chiếu `numeric_tree_array_bytes` với JSON Flower; giá trị mảng cây phải trùng nhưng không phải network bytes.

## 4. Cách trình bày trong báo cáo

- Một bảng gồm 5 client, region, số cây, `numeric_tree_array_bytes`, IP bytes lên/xuống, TCP payload lên/xuống, số packet; hàng cuối là tổng round. Ghi cùng `run_id`, seed, split SHA, UTC window và NIC capture.
- Một biểu đồ cột so sánh **IP bytes client→server** giữa client 1–5; có thể chú thích client 1–2 East Asia, 3–5 Korea Central. Ghi rõ kích thước model khác nhau theo số nút cây, không suy ra độ trễ chỉ từ byte.
- Một run đủ chứng minh có phép đo; nếu muốn kết luận ổn định về chi phí hoặc region, lặp lại ít nhất 3 run cùng cấu hình và báo trung vị/khoảng biến thiên.
- Nêu giới hạn: đo ở tầng IP của NIC server, có retransmission/handshake trong cửa sổ round, không bao gồm Ethernet FCS, traffic Blob 443, chi phí tính tiền Azure hay overhead ngoài TCP/8000. Không gọi con số này là số byte gRPC serialization thuần.
