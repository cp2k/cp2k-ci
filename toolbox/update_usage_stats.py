#!/usr/bin/env python3

# author: Ole Schuett

import sys
from datetime import datetime, timezone
from dataclasses import dataclass
from collections import defaultdict
from typing import Dict

import google.auth  # type: ignore
import google.cloud.storage  # type: ignore

gcp_project = google.auth.default()[1]
storage_client = google.cloud.storage.Client(project=gcp_project)
output_bucket = storage_client.get_bucket("cp2k-ci")

@dataclass
class Stats:
    count: int = 0
    hours: float = 0.0

stats_per_month_per_target: Dict[str, Dict[str, Stats]] = defaultdict(lambda: defaultdict(Stats))

report_iterator = output_bucket.list_blobs(prefix="run-")
for page in report_iterator.pages:
    print("Processing page {}".format(report_iterator.page_number))
    for report in page:
        meta = report.metadata
        if not meta or "cp2kci-started" not in meta or "cp2kci-updated" not in meta:
            continue  # without timestamps
        target = report.name.rsplit("-", 1)[0][4:]
        month = report.time_created.strftime("%Y-%m")
        started = datetime.fromisoformat(meta["cp2kci-started"])
        last_updated = datetime.fromisoformat(meta["cp2kci-updated"])
        duration = last_updated - started
        if duration.total_seconds() > 0:
            stats = stats_per_month_per_target[month][target]
            stats.count += 1
            stats.hours += duration.total_seconds() / 3600

usage_lines = []
for month in sorted(stats_per_month_per_target, reverse=True):
    usage_lines.append(f"########## CP2K-CI stats for {month} ##########\n")
    stats_per_target = stats_per_month_per_target[month]
    usage_lines.append("Target                          Count     Hours")
    usage_lines.append("-----------------------------------------------")
    for target, s in sorted(stats_per_target.items(), key=lambda kv: kv[1].hours, reverse=True):
        usage_lines.append(f"{target:30s} {s.count:6d} {s.hours:9.1f}")
    usage_lines.append("\n\n\n")

now = datetime.now(timezone.utc).replace(microsecond=0)
usage_lines.append("Last updated: " + now.isoformat())
usage_lines.append("")

usage_stats = "\n".join(usage_lines)
print("\n\n" + usage_stats)

# upload
if sys.argv[-1] == "--upload":
    usage_stats_blob = output_bucket.blob("usage_stats.txt")
    usage_stats_blob.cache_control = "no-cache"
    usage_stats_blob.upload_from_string(usage_stats)
    print("Uploaded to: " + usage_stats_blob.public_url)

# EOF
