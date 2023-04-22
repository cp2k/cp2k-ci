#!/usr/bin/python3

# author: Ole Schuett

import re
import sys

timing_pattern = re.compile(r"\d+(\.\d*)?")

for line in sys.stdin:
    parts = line.split(" ")
    if len(parts) > 1 and timing_pattern.fullmatch(parts[1]):
        sys.stdout.write(" ".join(parts[2:]))  # remove timing
    elif len(parts) > 2 and parts[1] == "pushing" and parts[2] == "layer":
        continue  # remove entire line
    elif len(parts) > 2 and parts[1] == "pulling" and parts[2].startswith("sha256:"):
        continue  # remove entire line
    else:
        sys.stdout.write(line)
    sys.stdout.flush()

# EOF
