# Federated Random Forest — Give Me Some Credit

The project contains two notebooks: [centralized EDA and Grid Search](notebooks/give_me_some_credit_eda_rf_gridsearch.ipynb) and [federated training and comparison](notebooks/federated_random_forest.ipynb). The Flower 1.42.0 app lives in `flower-app/fl_app`.

The shared protocol uses a stratified 60/20/20 split (seed 42), train-only median imputation, five disjoint client partitions, 20 trees per client and a 100-tree centralized comparator. Run the federated notebook from the repository root with `data/cs-training.csv` present. Generated split files are under `data/experiments/split_seed_42/`; local results are under `results/protocol_v1/`. These data and result files are not tracked in Git.

For distributed deployment, set `CLIENT_ID=1` through `CLIENT_ID=5` on the corresponding client VMs. The server verifies each client's partition SHA-256 and row count against the split summary. See the [Azure deployment handoff](deployment/azure/README.md) for data placement and environment variables. The local run does not establish that Azure networking, Blob transfer or TLS works.

For the full Azure procedure from resource setup through Flower, model export, and prediction API, see [HUONG_DAN_DAY_DU.md](deployment/azure/HUONG_DAN_DAY_DU.md).

Run local checks with `python -m unittest discover -s tests -v`.
