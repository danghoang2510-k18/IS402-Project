# Azure deployment handoff

For rubric-aligned VM, Blob, latency, experiment and cost monitoring, see [monitoring.md](monitoring.md). Use Azure Monitor Workbooks as the central view for both regions; configure host charts before the first distributed run and enable guest/Blob logs only for measurements that need them.

For model export and the web prediction API, see [inference_api.md](inference_api.md).

The local experiment and Flower app are ready to stage on Azure; no Azure deployment is claimed here. Pin Python, scikit-learn and Flower versions across the server and all clients before a distributed run. The Flower app requires Python >=3.11,<4.0 and pins Flower to 1.42.0 in `flower-app/pyproject.toml`; `requirements.txt` also pins Flower. Use the Flower 1.42 documentation for exact `SuperLink`/`SuperNode` commands and ports.

## Data and access

1. Run `notebooks/federated_random_forest.ipynb` locally with the approved source CSV. Preserve `data/experiments/split_seed_42/split_metadata.json` and `feature_schema.json` alongside the partition artifacts. Check the source and split SHA-256 values before uploading.
2. Store `client_1.csv` … `client_5.csv` from `data/experiments/split_seed_42/iid/clients_5/` as private blobs in separate client scopes. Give each client only read access to its own partition. Prefer Managed Identity with RBAC, or a short-lived read-only blob SAS. Do not send blob credentials in Flower messages.
3. Give every node the same `feature_schema.json`. Give the server only `validation.csv`, `test.csv`, `feature_schema.json` and `iid/clients_5/summary.json` (no raw client CSV files). Clients must not receive the evaluation files.
4. Set `PROJECT_DATA_ROOT` to the local `data` directory on the server. On each client VM set its fixed `CLIENT_ID` (1 through 5), `PROJECT_DATA_ROOT` for the schema, and `CLIENT_DATA_PATH` to its own partition file or `CLIENT_BLOB_URL` to its private blob URL. The server checks each returned client ID, partition SHA-256 and row count against `summary.json`. Set `PROJECT_RESULTS_ROOT` on the server to a writable result directory.

## Execution and checks

- Build/install `flower-app` on each node. Start with two clients, then five. Use the app's run configuration: `mode=iid`, `num-clients=5`, `trees-per-client=20`, `seed=42`. The server sends configuration and schema hash; each client returns 20 trees as numeric arrays. The server rejects duplicate IDs, schema mismatch and wrong total tree count.
- Compare the Flower output with the notebook's `results/protocol_v1/seed42_iid_clients5_trees20/` using the same source/split manifests. Flower selects its F1 threshold on validation before test evaluation. Save logs containing actual message sizes, transfer durations, upload/download bytes and VM topology; `numeric_payload_bytes` alone is not network traffic.
- Enable TLS and node authentication before traffic crosses an untrusted network. Keep Blob containers private. Store credentials only in environment/identity configuration, never notebooks or Git. Review model artifact access and retention because trees can leak information.
- For non-IID runs, first create the `non_iid/alpha_<value>/clients_5` partitions by changing the FL notebook configuration; pass matching `mode` and `alpha` in Flower run config. Retain the same train/validation/test split.

Cloud storage I/O, cross-region latency, web UI and costs require separate implementation and measured evidence. The inference API code is present, but deployment and API measurements remain to be performed on Azure. This handoff does not present local timings as Azure measurements.
