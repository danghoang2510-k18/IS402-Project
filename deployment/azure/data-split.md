# Thiết kế dữ liệu sau khi thêm `cs-test.csv`

| Nguồn | Vai trò | Số dòng | Có nhãn? | Được dùng để |
| --- | --- | ---: | --- | --- |
| `data/cs-training.csv` | Nguồn đánh giá nội bộ | 150.000 | Có | Chia phân tầng seed 42 thành train 90.000, validation 30.000, test 30.000. |
| `data/cs-test.csv` | Test ngoài mẫu của bộ dữ liệu | 101.503 | Không; toàn bộ `SeriousDlqin2yrs` trống | Chỉ suy luận sau huấn luyện, không tính AUC/AP/F1 và không chọn ngưỡng. |

Trong **train 90.000**, IID chia 5 partition có nhãn: `18001, 18000, 18000, 18000, 17999` dòng. Centralized học toàn bộ train; Flower cho mỗi client học đúng partition của mình. Median được fit trên train 90.000, rồi dùng nguyên giá trị ấy cho validation, test có nhãn và `cs-test.csv`. Test có nhãn 30.000 dòng vẫn là **cùng holdout** dùng để so sánh Centralized và FL.

`scripts/prepare_external_inference.py` tạo:

- `data/experiments/split_seed_42/external_inference.csv`: `source_row_id` từ file gốc và 10 đặc trưng theo `feature_schema.json`; không có cột nhãn.
- `data/experiments/split_seed_42/external_inference_metadata.json`: SHA nguồn/output, số dòng và số giá trị thiếu trước khi điền.

Hai file này độc lập với `split_metadata.json`, nên không thay đổi SHA và kết quả của split huấn luyện đã dùng trên Azure. Chạy:

```powershell
python scripts/prepare_external_inference.py
```

Sơ đồ Blob hai region: `storagedataflrf` (East Asia) lưu raw `cs-training.csv`, raw `cs-test.csv` trong `fl-source`, validation/test **có nhãn** trong `fl-eval`, dữ liệu **không nhãn** đã chuẩn bị trong `fl-inference`, và hai partition trong `client-1`/`client-2`. `storagedataflrf2` (Korea Central) lưu ba partition trong `client-3`/`client-4`/`client-5`. `artifacts` dành cho model/kết quả. Các client không nhận `cs-test.csv` hoặc holdout có nhãn.

Khi cần dự đoán 101.503 dòng, dùng model artifact và ngưỡng đã chọn trên validation; xuất `source_row_id`, xác suất và nhãn dự đoán. Không báo metric phân loại trên tập này khi chưa có nhãn thật.
