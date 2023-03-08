#!/usr/bin/python3

# author: Ole Schuett

import sys
from datetime import datetime
import google.auth
import google.cloud.storage

gcp_project = google.auth.default()[1]
storage_client = google.cloud.storage.Client(project=gcp_project)
output_bucket = storage_client.get_bucket("cp2k-ci")

ok_per_target = dict()
ok_per_month = dict()
err_per_target = dict()
err_per_month = dict()

report_iterator = output_bucket.list_blobs(prefix="run-")
for page in report_iterator.pages:
    print("Processing page {}".format(report_iterator.page_number))
    for report in page:
        error = report.size < 100
        target = report.name.rsplit("-", 1)[0][4:]
        month = report.time_created.strftime("%Y-%m")
        if report.size > 100:
            ok_per_target[target] = ok_per_target.get(target, 0) + 1
            ok_per_month[month] = ok_per_month.get(month, 0) + 1
        else:
            err_per_target[target] = err_per_target.get(target, 0) + 1
            err_per_month[month] = err_per_month.get(month, 0) + 1

usage_lines = []
usage_lines.append("###########  CP2K-CI USAGE STATS  ###########")
usage_lines.append("\n")

usage_lines.append("YEAR-MONTH              OK   ERR")
usage_lines.append("--------------------------------")
for month, count in sorted(ok_per_month.items(), key=lambda x: x[0]):
    errors = err_per_month.get(month, 0)
    bar = "x" * (count // 10) + "-" * (errors // 10)
    usage_lines.append("{:20s} {:5d} {:5d} {}".format(month, count, errors, bar))
usage_lines.append("\n")

usage_lines.append("TARGET                  OK   ERR")
usage_lines.append("--------------------------------")
for target, count in sorted(ok_per_target.items(), key=lambda x: -x[1]):
    errors = err_per_target.get(target, 0)
    bar = "x" * (count // 10) + "-" * (errors // 10)
    usage_lines.append("{:20s} {:5d} {:5d} {}".format(target, count, errors, bar))
usage_lines.append("\n")

now = datetime.utcnow().replace(microsecond=0)
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
