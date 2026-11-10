# Đối chiếu rubric và metric của thí nghiệm RF

Nguồn: sheet `Bài tập Lớn`, file `Rubik Đánh giá bài tập quá trình & Bài tập Lớn.xlsx` do nhóm cung cấp. Ba hướng tại hàng 24 là các trường hợp lựa chọn, không cộng gộp mọi yêu cầu Web/Trực quan/Phân tích thành một danh sách metric bắt buộc.

| Rubric | Cần chứng minh | Đầu ra hiện có hoặc nơi đo |
| --- | --- | --- |
| Hàng 6–7 | Kích thước dữ liệu, tốc độ xử lý cloud so với máy truyền thống | `source_file_bytes`, `train_seconds`, `flower_round_seconds` trong CSV; ghi rõ phần cứng và môi trường. Không coi thời gian hai máy khác cấu hình là speedup thuần thuật toán. |
| Hàng 18, 22 | Tốc độ đọc/ghi và tối ưu storage | Với `DATA_BACKEND=blob`: `blob_upload_metrics.csv`, `clients[*].blob_download_seconds`/`data_bytes`, `evaluation_blob_download_seconds` trong JSON Flower; đối chiếu Blob Metrics của Azure Monitor. |
| Hàng 19 | ETL tự động | `split_metadata.json`, `summary.json` và SHA; cần bằng chứng lịch chạy/pipeline nếu tuyên bố tự động. |
| Hàng 21 | Delay giữa region | Azure Connection Monitor hoặc phép đo TCP lặp lại từ từng region, có p50/p95, UTC interval và đích. Không suy ra RTT từ `flower_round_seconds`. |
| Hàng 34–37, nhánh Phân tích | Huấn luyện model, API, trực quan so sánh | CSV `comparison_metrics.csv`: AUC, AP, Brier, accuracy, balanced accuracy, precision, recall, specificity, F1, FPR/FNR, confusion matrix, ngưỡng validation; FastAPI `/predict`, `/dashboard` và trang web. |
| Hàng 44 | Chi phí và quota | Azure Cost Analysis, quota theo region và khoảng thời gian; không có số chi phí tự sinh từ code huấn luyện. |

`numeric_payload_bytes` chỉ là kích thước các mảng số của cây, **không phải** tổng byte trên mạng. Các số CPU/RAM/network của VM, latency liên vùng và chi phí lấy từ Azure Monitor/Cost Analysis; không điền ước lượng vào CSV đánh giá mô hình.

Đề Bài tập 15 yêu cầu communication cost theo vòng. Run Azure `2172526506691903996` đã ghi mốc UTC đầu/cuối vòng; `results/azure_traffic_new_run/flower_traffic_round1.json` có IP/TCP bytes hai chiều theo client từ packet capture TCP/8000. Tổng vòng 1 là 4.275.944 IP bytes. [communication-cost.md](communication-cost.md) ghi phương pháp và giới hạn phép đo. Notebook FL có Grid Search 3-fold chỉ trên Train, bảng/hình CV AP và file `tuning_results.csv`; kết quả tuning không âm thầm thay tham số của run Azure đã có.

## Giao thức so sánh

- `notebooks/centralized_random_forest.ipynb` có EDA, Grid Search và baseline tập trung cố định 100 cây trên đúng split của Flower; xuất `results/centralized_seed42_fixed/`. `notebooks/federated_random_forest.ipynb` trình bày thêm các Client, aggregation và FL mô phỏng. Không dùng hàng Grid Search bất kỳ làm baseline đối chứng Azure.
- Cùng source, split seed 42 (train/validation/test 60/20/20), median fit trên train, 10 đặc trưng, test 30.000 hàng, 100 cây, `max_depth=10`, `min_samples_leaf=5`, `max_features=sqrt`, `class_weight=None`. FL IID có 5 client × 20 cây; central fit toàn bộ train. Random state của central và từng client khác nhau có chủ đích.
- Cùng hàm `fl_app.evaluation` chọn ba ngưỡng trên validation và tính metric trên test. AUC/AP/Brier không phụ thuộc ngưỡng; các metric confusion phụ thuộc ngưỡng. File CSV có 6 hàng (2 mô hình × 3 chính sách).
- `train_seconds` là thời gian fit central. `flower_round_seconds` bao gồm gửi, nhận và chờ phản hồi; `max_client_train_seconds` chỉ là client lâu nhất. Không so sánh hai cột này như speedup đồng cấu hình khi central chạy local và Flower chạy Azure.

## Tạo một file so sánh

Chạy lại notebook sau khi cập nhật. Từ thư mục gốc dự án:

```powershell
python scripts/build_comparison.py
```

Lệnh trên viết `results/comparison_metrics.csv` từ **mô phỏng local**. Sau khi triển khai mã Flower mới lên 6 VM và chạy lại IID, tải JSON kết quả mới về, rồi dùng:

```powershell
python scripts/build_comparison.py --flower "C:\path\to\flower_seed42_iid_clients5.json" --output results/comparison_metrics_azure.csv
```

Lệnh từ chối kết quả cũ thiếu metric hoặc không khớp SHA source/split, schema, tham số RF và số cây. CSV Azure chỉ có số liệu thật khi Flower mới chạy xong; không ghép JSON Azure cũ với notebook mới.
