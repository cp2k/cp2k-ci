#!/usr/bin/python3

# author: Ole Schuett

import re
import sys

timing_pattern = re.compile(r"\d+(\.\d*)?")

for line in sys.stdin:
    parts = line.split(" ")
    if len(parts) > 1 and timing_pattern.fullmatch(parts[1]):
        sys.stdout.write(" ".join(parts[2:]))
    else:
        sys.stdout.write(line)

# EOF
