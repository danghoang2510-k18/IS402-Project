"""Read private Azure blobs using the VM's managed identity."""

from __future__ import annotations

import time
from urllib.parse import urlsplit


def download_blob(url: str) -> tuple[bytes, float]:
    if urlsplit(url).scheme != "https":
        raise ValueError("Blob URL must use HTTPS")
    # Import only in Blob mode so local CSV experiments need no Azure SDK.
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobClient

    started = time.perf_counter()
    # A URL carrying a scoped SAS is supported for deployments without RBAC.
    credential = None if urlsplit(url).query else DefaultAzureCredential()
    client = BlobClient.from_blob_url(url, credential=credential)
    data = client.download_blob(max_concurrency=1).readall()
    return data, time.perf_counter() - started
