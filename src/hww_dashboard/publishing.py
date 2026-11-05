"""Serialise GCP reads and publication across the job and the workflow."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def publication_lock(config_path: str | Path) -> Iterator[None]:
    """Hold one lease while a GCP reporting snapshot is rebuilt.

    Local runs rely on the caller to serialise writes. GitHub also
    serialises workflow invocations; the storage lease covers overlap
    with a Cloud Run job. Only the GCP target needs py-common, so it is
    imported only there.

    Args:
        config_path: HWW configuration file.

    Yields:
        Control while the publication lease is held.
    """
    from hww_dashboard.wrangle import load_config

    path = Path(config_path).resolve()
    cfg = load_config(path)
    if cfg.get("landed", {}).get("target", "local") != "gcp":
        yield
        return
    from py_common.adapters.gcs import GCSObjectStore
    from py_common.model import digest

    from hww_dashboard.landing import landing_settings

    settings = landing_settings(cfg, path.parent)
    output = cfg.get("output", {})
    dataset = output.get("dataset", settings.dataset)
    destination = f"{settings.project}.{dataset}"
    store = GCSObjectStore(settings.project, settings.store_bucket)
    with store.lock(f"locks/publication/{digest(destination.encode())}"):
        yield
