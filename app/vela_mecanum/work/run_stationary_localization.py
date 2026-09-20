from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "outputs" / "formation-kit"
sys.path.insert(0, str(KIT))

import run_autonomous_formation as control
from formation_planner import ROBOT_IDS


def main() -> None:
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(control.localize_car, ROBOT_IDS))
    for result in results:
        print(result)
    print("STATIONARY_LOCALIZATION_OK")


if __name__ == "__main__":
    main()
