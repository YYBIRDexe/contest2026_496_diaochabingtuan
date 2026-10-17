"""Offline scan-to-map search against the currently deployed map."""

from pathlib import Path
import math
import re
import time
import numpy as np
from PIL import Image, ImageFilter

ROOT=Path(__file__).resolve().parent/'current_map'
image=Image.open(ROOT/'classroom.pgm').convert('L')
width,height=image.size
resolution=0.05
origin_x,origin_y=-4.61,-4.1
field=np.asarray(image.point(lambda p:255 if p<100 else 0).filter(ImageFilter.GaussianBlur(radius=2.5)),dtype=np.float32)/255.0

def scan(index):
    raw=(ROOT/f'robot{index}_scan_raw.txt').read_text()
    angle_min=float(re.search(r'^angle_min: ([^\n]+)',raw,re.M).group(1))
    step=float(re.search(r'^angle_increment: ([^\n]+)',raw,re.M).group(1))
    block=raw.split('ranges:\n',1)[1].split('intensities:',1)[0]
    ranges=np.array([float(v.replace('.nan','nan')) for v in re.findall(r'^- ([^\n]+)$',block,re.M)])
    angles=angle_min+np.arange(len(ranges))*step
    valid=np.isfinite(ranges)&(ranges>0.38)&(ranges<8.0)&(np.arange(len(ranges))%2==0)
    return ranges[valid]*np.cos(angles[valid]),ranges[valid]*np.sin(angles[valid])

def score_grid(local_x,local_y,xs,ys,yaw):
    c,s=math.cos(yaw),math.sin(yaw)
    rx=c*local_x-s*local_y-0.012*c
    ry=s*local_x+c*local_y-0.012*s
    gx,gy=np.meshgrid(xs,ys,indexing='xy')
    px=np.rint((gx[...,None]+rx-origin_x)/resolution).astype(np.int32)
    py=np.rint(height-1-(gy[...,None]+ry-origin_y)/resolution).astype(np.int32)
    valid=(px>=0)&(px<width)&(py>=0)&(py<height)
    result=np.zeros(px.shape,dtype=np.float32)
    result[valid]=field[py[valid],px[valid]]
    return result.mean(axis=-1)

for index in range(1,5):
    start=time.monotonic()
    local_x,local_y=scan(index)
    xs=np.arange(-3,3.001,.2)
    ys=np.arange(-3,3.001,.2)
    candidates=[]
    for yaw in np.arange(-math.pi,math.pi,math.radians(10)):
        scores=score_grid(local_x,local_y,xs,ys,yaw)
        for flat in np.argpartition(scores.ravel(),-5)[-5:]:
            iy,ix=np.unravel_index(flat,scores.shape)
            candidates.append((float(scores[iy,ix]),float(xs[ix]),float(ys[iy]),float(yaw)))
    candidates.sort(reverse=True)
    fine=[]
    for _,x,y,yaw in candidates[:20]:
        for fyaw in np.arange(yaw-math.radians(8),yaw+math.radians(8.1),math.radians(2)):
            fxs=np.arange(x-.15,x+.151,.05)
            fys=np.arange(y-.15,y+.151,.05)
            scores=score_grid(local_x,local_y,fxs,fys,fyaw)
            iy,ix=np.unravel_index(np.argmax(scores),scores.shape)
            fine.append((float(scores[iy,ix]),float(fxs[ix]),float(fys[iy]),float(fyaw)))
    fine.sort(reverse=True)
    distinct=[]
    for score,x,y,yaw in fine:
        if any(math.hypot(x-vx,y-vy)<.3 and abs(math.atan2(math.sin(yaw-vyaw),math.cos(yaw-vyaw)))<.3 for _,vx,vy,vyaw in distinct):
            continue
        distinct.append((score,x,y,yaw))
        if len(distinct)>=5:break
    print(index,len(local_x),'time',round(time.monotonic()-start,2),'top',distinct,flush=True)
