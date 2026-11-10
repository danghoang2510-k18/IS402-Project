# Serving the federated forest on Azure

**Luồng hiện dùng:** model và metrics được upload vào `artifacts/runs/<run_id>/`, API đọc `latest-iid.json` để tự đổi model. Xem [model-artifacts.md](model-artifacts.md). Các lệnh `MODEL_DIR` bên dưới là chế độ local/fallback để thử một run cố định.

The Flower run writes metrics and a separate model directory on the server VM:

```text
results/
  flower_seed42_iid_clients5.json
  models/run_<flower_run_id>/
    model.json
    forest.npz
```

`model.json` records the feature order, training medians, validation-selected threshold,
run ID, tree count and array checksum. `forest.npz` contains numeric tree arrays and
is read with `allow_pickle=False`. The model directory contains no raw client CSVs.
Run IID hiện tại đã có model artifact trên server; có thể publish run này lên
Blob mà không huấn luyện lại theo [model-artifacts.md](model-artifacts.md).

## Deploy the updated code

From PowerShell on the Windows project machine:

```powershell
$project = "C:\Users\ACER\Documents\ChatGPT\Project Cloud"
scp "$project\flower-app\fl_app\server_app.py" `
    "$project\flower-app\fl_app\client_app.py" `
    "$project\flower-app\fl_app\evaluation.py" `
    "$project\flower-app\fl_app\model_artifact.py" `
    "$project\flower-app\fl_app\api.py" `
    vm-fl-server:/home/azureuser/project-cloud/flower-app/fl_app/
scp "$project\flower-app\pyproject.toml" `
    vm-fl-server:/home/azureuser/project-cloud/flower-app/pyproject.toml
scp "$project\data\experiments\split_seed_42\split_metadata.json" `
    vm-fl-server:/home/azureuser/project-cloud/data/experiments/split_seed_42/
```

The clients need no code update for this change. On the server, keep the existing
SuperLink and five SuperNodes running, then:

```bash
source ~/fl-venv/bin/activate
cd ~/project-cloud/flower-app
python -m pip install -e .
export PROJECT_DATA_ROOT=/home/azureuser/project-cloud/data
export PROJECT_RESULTS_ROOT=/home/azureuser/project-cloud/results
flwr run . azure-private --stream
```

Confirm the run printed metrics and that its new `model_artifact` path exists.
Set `MODEL_DIR` to the containing `run_<flower_run_id>` directory. The API loads
the model once and applies the feature order, medians and threshold saved with it:

```bash
export MODEL_DIR=/home/azureuser/project-cloud/results/models/run_<flower_run_id>
uvicorn fl_app.api:app --host 127.0.0.1 --port 8080
```

In another shell on the server:

```bash
curl http://127.0.0.1:8080/healthz
curl http://127.0.0.1:8080/dashboard
curl -X POST http://127.0.0.1:8080/predict \
  -H 'Content-Type: application/json' \
  -d '{"features":{"RevolvingUtilizationOfUnsecuredLines":0.15,"age":52,"NumberOfTime30-59DaysPastDueNotWorse":0,"DebtRatio":0.37,"MonthlyIncome":5400,"NumberOfOpenCreditLinesAndLoans":8,"NumberOfTimes90DaysLate":0,"NumberRealEstateLoansOrLines":1,"NumberOfTime60-89DaysPastDueNotWorse":0,"NumberOfDependents":0}}'
```

The response contains `risk_probability`, `predicted_label`, `threshold`,
`imputed_features`, `model_run_id`, and `mode`. Missing or null features are filled
with training medians; unknown feature names and non-finite values are rejected.
The web form should send a JSON request to this endpoint and display the risk
probability and model version. For an initial demo, serve the web page and API
through one HTTPS reverse proxy on the server VM. Keep Uvicorn bound to loopback;
do not expose port 8080 through the NSG. Add authentication and request logging
before allowing external users to submit data. Azure Monitor can collect API
request count, errors and latency once the web/API service is running.

The frontend source is in `web/`, with deployment commands in
`deployment/azure/web-api.md`. `GET /dashboard` returns selected FL and
centralized metrics; it does not expose raw client data.
