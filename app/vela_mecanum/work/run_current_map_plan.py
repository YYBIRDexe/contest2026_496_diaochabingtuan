from pathlib import Path
import time
from formation_planner import FormationPlanner, OccupancyGrid, Pose, Request
from scan_localizer import ScanMatcher, parse_scan_echo, map_metadata

root=Path('/home/vela/formation-sim/current_map')
pgm=root/'classroom.pgm'
matcher=ScanMatcher(pgm)
current={}
for index in range(1,5):
    estimate=matcher.estimate(*parse_scan_echo(root/f'robot{index}_scan_raw.txt'))
    current[f'robot{index}']=Pose(estimate.x,estimate.y,estimate.yaw)
print('poses',current,flush=True)
resolution,origin=map_metadata(pgm)
grid=OccupancyGrid(pgm,resolution,origin)
planner=FormationPlanner(arena=(-3.3,3.3,-3.3,3.3),map_grid=grid)
for shape in ('square','line','circle','diamond'):
    started=time.monotonic()
    try:
        plan=planner.plan(current,Request(shape,.5))
        planner.verify(current,plan)
        print(shape,'OK','steps',len(plan.steps),'slots',plan.slots,'time',round(time.monotonic()-started,2),flush=True)
    except Exception as exc:
        print(shape,'BLOCKED',str(exc),'time',round(time.monotonic()-started,2),flush=True)
