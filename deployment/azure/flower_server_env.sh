#!/usr/bin/env bash
# Source this file in the shell that starts SuperLink and in the shell running flwr run.
export DATA_BACKEND=blob
export EVAL_BLOB_BASE_URL=https://storagedataflrf.blob.core.windows.net/fl-eval
export ARTIFACT_BLOB_BASE_URL=https://storagedataflrf.blob.core.windows.net/artifacts
export PROJECT_DATA_ROOT=/home/azureuser/project-cloud/data
export PROJECT_RESULTS_ROOT=/home/azureuser/project-cloud/results
