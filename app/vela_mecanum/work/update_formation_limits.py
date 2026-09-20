import json
from pathlib import Path
import sys


config = Path(sys.argv[1])
verify = len(sys.argv) > 2 and sys.argv[2] == "--verify"
data = json.loads(config.read_text(encoding="utf-8"))
if data.get("hardware_output_enabled") is not True:
    raise SystemExit("hardware output configuration is not enabled")
limits = data["limits"]
if verify:
    if limits["max_linear_mps"] != 0.875 or limits["max_acceleration_mps2"] != 2.0:
        raise SystemExit("formation speed limits do not match")
    print("limits_verified")
else:
    limits["max_linear_mps"] = 0.875
    limits["max_acceleration_mps2"] = 2.0
    config.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
