# Azure Monitor cho thí nghiệm Federated Random Forest

Tài liệu này là hướng dẫn cấu hình và thu thập bằng chứng. Chưa có bằng chứng rằng Azure Monitor, Blob Storage hay API đã được bật trên subscription. Thí nghiệm hiện tại chép CSV bằng SCP; số liệu Blob chỉ có sau khi thực sự chạy thí nghiệm với Azure Blob Storage.

## 1. Liên hệ với rubric gốc

Nguồn đã kiểm tra trực tiếp: `C:\Users\ACER\Downloads\Rubik Đánh giá bài tập quá trình & Bài tập Lớn.xlsx`, sheet `Bài tập Lớn` (các số hàng dưới đây là số hàng Excel). Hàng 24 cho chọn một trong ba hướng Web, Trực quan dữ liệu, Phân tích dữ liệu. Dự án này theo hướng Phân tích dữ liệu (hàng 34–37); hàng 25–33 là tiêu chí của hai hướng khác, không mặc nhiên bắt buộc cho dự án này.

| Rubric | Số đo cần lưu | Nguồn bằng chứng | Giới hạn |
| --- | --- | --- | --- |
| Hàng 6–7: dung lượng và tốc độ xử lý local/cloud | Kích thước CSV, số hàng, thời gian huấn luyện, CPU/RAM, cấu hình VM | Manifest dữ liệu + log Centralized/FL + VM Metrics/VM Insights | Khác số vCPU hoặc region phải được ghi rõ, không quy mọi chênh lệch cho FL. |
| Hàng 18: tốc độ đọc/ghi | MB/s và thời gian từng lần upload/download Blob; `Ingress`, `Egress`, `Transactions`, `SuccessE2ELatency`, `SuccessServerLatency` | Benchmark trong ứng dụng + Azure Blob Metrics | Disk I/O của VM và SCP không thay thế phép đo Blob Storage. |
| Hàng 19: ETL tự động | Thời điểm bắt đầu/kết thúc, số bản ghi, trạng thái, checksum, lỗi | Log pipeline/manifest có `run_id` | Azure Monitor không tự tạo pipeline ETL. |
| Hàng 21: độ trễ khác region | `RoundTripTimeMs`, `ChecksFailedPercent`, TCP connect time từ từng client đến private IP server; p50/p95 qua nhiều lần | Network Watcher Connection Monitor + bài đo riêng trên VM + ghi region/VNet/IP | VM Network In/Out không phải phép đo độ trễ peering. |
| Hàng 22: tối ưu lưu trữ và I/O | Trước/sau: thời gian, throughput, byte, lỗi, cùng kích thước đầu vào | Benchmark ứng dụng + Blob Metrics | Chỉ kết luận cải thiện khi cùng điều kiện so sánh. |
| Hàng 34–36: model và trực quan | ROC-AUC, AP, F1, precision, recall, confusion matrix, số cây, thời gian, payload | JSON kết quả Flower và notebook centralized; biểu đồ kết quả | Azure Monitor không tự tính chất lượng model; `numeric_payload_bytes` không phải byte mạng thực tế. |
| Hàng 35, 37: API và web | Số request, tỷ lệ lỗi, p50/p95 response time, kết quả trả về | Log/API instrumentation khi API đã triển khai | Chưa có API thì chưa có số đo này. |
| Hàng 44: chi phí và quota | Cost Analysis, Budget, quota vCPU/Public IP, thời gian VM chạy | Azure Cost Management + Quotas + Activity Log | Azure Monitor Metrics không thay thế thông tin hóa đơn/quota. |

## 2. Azure Monitor là nơi xem tập trung

Vào **Azure Portal → Monitor** thay vì mở từng VM làm điểm xuất phát. Tạo **một Azure Monitor Workbook** cho thí nghiệm tại **Monitor → Workbooks → New**, đặt tên chẳng hạn `FL-RF-Experiment`, lưu trong resource group dự án. Thêm tham số thời gian và ghi `run_id`, seed, topology vào phần mô tả của mỗi lần lưu bằng chứng. Workbook có thể chứa nhiều chart metric, truy vấn Log Analytics và phần giải thích trên cùng một trang.

### 2.1 Host metrics sẵn có, không cần agent

Tại **Monitor → Metrics → Select a scope**, chọn ba VM ở **East Asia**, cùng resource type `Virtual machines`; tạo chart `Percentage CPU` (Average/Maximum), `Network In Total` và `Network Out Total` (Sum), `Disk Read Bytes` và `Disk Write Bytes` (Sum), granularity **1 minute**. Lặp lại với ba VM ở **Korea Central**. Đưa chart hoặc metric query của từng region vào cùng Workbook; đặt tên rõ `East Asia` và `Korea Central`.

**Giới hạn quan trọng:** một multi-resource chart trong Metrics Explorer chỉ chọn được tài nguyên cùng subscription, loại tài nguyên và **region**. Vì vậy không chọn cả sáu VM khác region trong một scope/chart; Workbook là nơi ghép hai nhóm chart để xem tập trung. Khi so sánh, dùng cùng UTC time range, cùng metric và aggregation. Host metrics và Activity Log có sẵn; không phải cài Azure Monitor Agent để có các metric này.

Network totals gồm mọi lưu lượng VM (SSH, agent, Flower...), nên chỉ dùng làm bằng chứng tài nguyên; không gọi đó là chính xác số byte payload Flower. Lưu VM SKU/vCPU/RAM và UTC start/end bên cạnh chart.

### 2.2 Một workspace cho guest RAM và log (tùy chọn có chi phí)

Host metrics không cung cấp RAM guest mặc định. Nếu rubric/report cần RAM và log tập trung, vào **Monitor → Log Analytics workspaces → Create**; tạo một workspace trong resource group dự án, chọn region hỗ trợ và retention ngắn phù hợp kỳ thí nghiệm. Sau đó vào **Monitor → Data Collection Rules → Create**: chọn Linux performance counters cần thiết (CPU, available memory, disk, network), destination là workspace vừa tạo, gắn DCR vào **cả sáu VM**. Azure Portal có thể cài Azure Monitor Agent khi gắn DCR. DCR phải ở cùng region với workspace; các VM được theo dõi có thể thuộc region khác.

Có thể dùng **Monitor → Virtual Machines/VM Insights → Enable enhanced monitoring** làm luồng giao diện thay thế, chọn cùng workspace và tái sử dụng DCR phù hợp để tránh thu trùng dữ liệu. Trong **Monitor → Logs**, đặt scope là workspace và kiểm tra `InsightsMetrics` có hàng của cả sáu `Computer`; thêm một Log Analytics query từ workspace vào Workbook. Không bật dependency/process map hoặc toàn bộ Syslog nếu không cần.

Azure Monitor Agent cần HTTPS outbound tới dịch vụ Azure Monitor. Nếu bật lại private subnet, phải chuẩn bị đường outbound hoặc Private Link phù hợp; peering giữa hai VNet không thay thế outbound này. Workspace/VM Insights có thể phát sinh phí ingestion/retention. Nếu không dùng workspace, chỉ số RAM phải được ghi bằng công cụ local trên VM và lưu riêng.

## 4. Azure Blob Storage: chỉ bật khi có bài đo Blob thật

Trên Storage Account → **Monitoring → Metrics**, chọn phạm vi **Blob service** và biểu đồ `Ingress`, `Egress`, `Transactions`, `SuccessE2ELatency`, `SuccessServerLatency` (granularity 1 minute). Lọc `ApiName` như `PutBlob`/`GetBlob` khi khả dụng. Số đo service latency không phải toàn bộ thời gian tải file mà ứng dụng nhìn thấy, nên đồng thời ghi timestamp, kích thước byte và elapsed time từ client benchmark.

Nếu cần log từng thao tác, mở **Storage Account → Blob service → Monitoring → Diagnostic settings**; tạo diagnostic setting gửi các nhóm `StorageRead`, `StorageWrite`, `StorageDelete` cần dùng tới Log Analytics workspace. Chỉ bật loại cần đo vì log có phí. Kiểm tra bảng `StorageBlobLogs` sau khi thực hiện upload/download mẫu. Với thí nghiệm SCP hiện tại, các biểu đồ Blob không chứng minh tốc độ đọc/ghi dữ liệu thí nghiệm.

## 5. Đo region latency và Flower run

- Trong **Network Watcher → Connection monitor**, tạo test group với nguồn `vm-fl-client-1`…`5`, đích là private IP hoặc VM `vm-fl-server`, giao thức TCP, cổng Flower thực tế (sau khi SuperLink lắng nghe). Xem `RoundTripTimeMs`, `ChecksFailedPercent` và `TestResult`; lọc theo `SourceName` để so sánh East Asia với Korea Central và thêm chart vào Azure Monitor Workbook. Giữ cùng thời gian đo và cấu hình test. Connection Monitor có thể dùng Network Watcher extension và Log Analytics tùy cấu hình; kiểm tra chi phí trước khi bật liên tục.
- Khi SuperLink đã lắng nghe trên private IP, đo nhiều lần TCP connect time từ từng client tới private IP server và port thực tế; lưu từng mẫu và p50/p95. Dùng cùng phương pháp, thời điểm, số lần đo ở East Asia và Korea Central. Ping ICMP có thể bị chặn nên không dùng một lần ping làm kết luận.
- Ghi `run_id`, `mode`, `seed`, `num_clients`, `trees_per_client`, thời gian UTC bắt đầu/kết thúc, SHA-256 partition, số hàng, tổng 100 cây, kết quả trên cùng validation/test. Giữ log SuperLink/SuperNode và JSON output của ServerApp.
- Tính thời gian end-to-end bằng đồng hồ monotonic của ứng dụng hoặc lệnh đo bọc quanh toàn run. `numeric_payload_bytes` hiện là tổng NumPy array bytes, không gồm gRPC/TLS/Flower protocol; lưu VM network metrics bên cạnh nhưng không đánh đồng hai số.
- So sánh Centralized và FL với cùng split/seed/test. So sánh cross-region cần thêm topology 2 client East Asia + 3 client Korea Central; không suy ra hiệu ứng region chỉ từ một run tổng hợp.

## 6. Chi phí, cảnh báo và bằng chứng

Vào **Cost Management → Cost analysis** và **Budgets** ở subscription/resource group, tạo ngân sách theo credit còn lại do nhóm tự chọn; xem **Quotas** cho từng region và family vCPU/Public IP. Chụp ảnh/tải số liệu sau ngày chạy vì cost data có độ trễ. Azure Monitor Metrics không phải nguồn chi phí.

Trước mỗi run, tạo thư mục bằng chứng theo `run_id` (ví dụ `results/azure/<run_id>/`) với: manifest tham số, topology/VM SKU/region, UTC interval, JSON kết quả, log Flower, CSV hoặc ảnh Azure Monitor VM/Blob, benchmark latency, Cost Analysis/quota. Không lưu SAS, khóa hay dữ liệu khách hàng trong log/ảnh công khai.

## Nguồn Microsoft

- [VM host và guest monitoring](https://learn.microsoft.com/en-us/azure/azure-monitor/vm/monitor-virtual-machine-data-collection)
- [VM metric names](https://learn.microsoft.com/en-us/azure/virtual-machines/monitor-vm-reference)
- [Bật giám sát VM](https://learn.microsoft.com/en-us/azure/azure-monitor/vm/tutorial-enable-monitoring)
- [Blob metrics](https://learn.microsoft.com/en-us/azure/storage/blobs/monitor-blob-storage-reference)
- [Network Watcher Connection Monitor](https://learn.microsoft.com/en-us/azure/network-watcher/connection-monitor-overview)
- [StorageBlobLogs](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/queries/storagebloblogs)
- [Azure Monitor costs](https://learn.microsoft.com/en-us/azure/azure-monitor/usage-estimated-costs)
- [Azure for Students cost/budget](https://learn.microsoft.com/en-us/azure/education-hub/navigate-costs)
