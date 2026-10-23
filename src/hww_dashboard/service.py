"""Upload-triggered Cloud Run service: ingest the folder, then rebuild.

A workbook uploaded to the landing bucket publishes a notification to
Pub/Sub, and an Eventarc trigger delivers it here (docs/gcp_ingestion.md,
step 9). ``on_upload``:

1. runs py-common's ``handle_upload``, which ingests every file in the
   folder the upload landed in (``hww/was/`` and so on), under the same
   lock as the daily job, so the two never load at once. A folder
   that feeds several tables (``hww/signups/``, the monitoring
   workbook: signups and survey) runs each table's pipeline in turn;
2. if nothing was quarantined or failed, rebuilds the reporting tables
   with the pipeline, reading the newest load of every source.

What happens to the event:

- a folder with no pipeline, another bucket, or a non-upload event:
  ignored (logged, not retried);
- a file quarantined: the tables aren't rebuilt, and the event isn't
  retried, as retrying won't fix the file; the quarantine is logged at
  ERROR for alerts;
- the rebuild stops on a problem a person must fix (a mapping, a
  setting): logged at ERROR, not retried;
- a file FAILED, the lock is held, or the rebuild fails unexpectedly:
  the error is raised, so Pub/Sub delivers the event again. A
  redelivery finds the files already loaded and simply rebuilds.

The functions-framework runs it in the image:
``functions-framework --source=<this file> --target=on_upload
--signature-type=cloudevent``. ``HWW_CONFIG`` names the config
(``/app/config.gcp.toml`` by default).
"""

import logging
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from py_common.model import Outcome, Result
from py_common.pipeline import Pipeline
from py_common.runner import handle_upload, parse_upload

from hww_dashboard import wrangle
from hww_dashboard.landing import (
    build_pipelines,
    landing_folders,
    landing_settings,
)
from hww_dashboard.logs import (
    close_logging,
    configure_logging,
    log_format,
    new_run_id,
)

logger = logging.getLogger("hww_dashboard.service")

DEFAULT_CONFIG = "/app/config.gcp.toml"


class CloudEvent(Protocol):
    """The part of a CloudEvent the service reads."""

    @property
    def data(self) -> Mapping[str, Any]:
        """The Pub/Sub message carrying the GCS notification."""
        ...


def folder_pipelines(config_path: Path) -> dict[str, list[Pipeline]]:
    """The sources' pipelines, grouped by the landing folder they read.

    Args:
        config_path: The config file.

    Returns:
        Pipelines per folder, e.g. "hww/signups": [signups, survey].
    """
    cfg = wrangle.load_config(config_path)
    base = config_path.parent
    maps = (base / cfg["paths"]["mappings_folder"]).resolve()
    settings = landing_settings(cfg, base)
    folders = landing_folders(cfg)
    grouped: dict[str, list[Pipeline]] = {}
    for source, pipeline in build_pipelines(cfg, maps, settings).items():
        folder = "/".join(
            p for p in (settings.landing_prefix, folders[source]) if p
        )
        grouped.setdefault(folder, []).append(pipeline)
    return grouped


def ingest_upload(
    data: Mapping[str, Any], pipelines: Mapping[str, Sequence[Pipeline]]
) -> list[Result]:
    """Run every pipeline that reads the folder an upload went to.

    py-common's handle_upload runs one pipeline per folder, so it is
    called first with each folder's first pipeline, which also decides
    whether the event is ignored. If it isn't, handle_upload is called
    again for each further pipeline of the upload's folder. Each
    pipeline has its own lock and "already loaded" markers.

    Args:
        data: The CloudEvent's data.
        pipelines: Pipelines per landing folder, from folder_pipelines.

    Returns:
        Every pipeline's results; empty if the event was ignored.

    Raises:
        RunFailed: A file FAILED (from py-common); retried.
        RuntimeError: Another run holds the lock; retried.
    """
    results = handle_upload(
        data, {folder: group[0] for folder, group in pipelines.items()}
    )
    if not results:
        return results
    folder = parse_upload(data).folder.strip("/")
    for pipeline in pipelines.get(folder, [])[1:]:
        results.extend(handle_upload(data, {folder: pipeline}))
    return results


def handle(
    data: Mapping[str, Any],
    config_path: Path,
    rebuild: Callable[[Path], object] | None = None,
) -> str:
    """Ingest the upload's folder, then rebuild the tables if all is well.

    Args:
        data: The CloudEvent's data.
        config_path: The config file.
        rebuild: Builds the reporting tables (wrangle.run by default).

    Returns:
        What happened: "ignored", "quarantined", "rebuild stopped" or
        "rebuilt".

    Raises:
        RunFailed: A file FAILED (from py-common); retried.
        RuntimeError: Another run holds the lock; retried.
        Exception: The rebuild failed unexpectedly; retried.
    """
    results = ingest_upload(data, folder_pipelines(config_path))
    if not results:
        return "ignored"
    quarantined = [r for r in results if r.outcome == Outcome.QUARANTINED]
    if quarantined:
        for result in quarantined:
            logger.error(
                "Quarantined %s; tables not rebuilt: %s",
                result.item.name,
                "; ".join(result.errors),
            )
        return "quarantined"
    try:
        (rebuild or wrangle.run)(config_path)
    except wrangle.InputError as error:
        logger.error("Stopped rebuilding the tables: %s", error)
        return "rebuild stopped"
    return "rebuilt"


def on_upload(event: CloudEvent) -> None:
    """Cloud Run entry point for an Eventarc upload event.

    Args:
        event: The CloudEvent from Eventarc's Pub/Sub trigger.
    """
    handlers = configure_logging(new_run_id(), log_format())
    library = logging.getLogger("py_common")
    library.setLevel(logging.INFO)
    for handler in handlers:
        library.addHandler(handler)
    try:
        config = Path(os.environ.get("HWW_CONFIG", DEFAULT_CONFIG))
        outcome = handle(event.data, config)
        logger.info("Upload handled: %s", outcome)
    finally:
        for handler in handlers:
            library.removeHandler(handler)
        close_logging(handlers)
