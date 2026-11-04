/**
 * VelaGuard · 端侧预设表（openvela 快应用版）
 *
 * 这个文件就是方案二功能一「巡检区域与任务清单管理」的全部数据：
 *   - MAP       地图（**车端真实 ROS 地图**转出来的矢量轮廓 + 米格网）
 *   - WAYPOINTS 航点坐标（地图坐标系，单位米）
 *   - ROUTES    四条**预设好的固定路线**，路线 = 航点序列，没有自由坐标
 *   - ZONES     四个区域 → 四条路线 → 四台车的登记表
 *
 * 设计约束（有意为之，别随手放宽）：
 *  1. 路线只由**航点编号**组成，任务单里不出现坐标/速度/时长。
 *     车端拿到的只是「执行 route_entrance」，无法被诱导跑任意轨迹。
 *  2. 坐标是**地图坐标系（米）**，与车端 ROS 地图同一套，不是屏幕像素。
 *     屏幕换算只在 map.js 里做，换屏、换任务都不用动这里。
 *  3. 每条路线都短：**2~3 段、总长 ≤ 3.5 m、每段 ≤ 1.0 m**。
 *     小车行为只用最朴素的原语：直行 + 到点停留 + 转向下一段。
 *  4. 四条路线**互不重叠地分布在四块区域**，同一屏上都能看清。
 *
 * ⚠️ 坐标基准来自车端当前生效地图：
 *      classroom.pgm，350×197 格，0.05 m/格，原点 [-4.61, -4.1, 0]
 *      可行区域包围盒 x ∈ [-4.51, 12.84]，y ∈ [-3.85, 5.70]
 *    地图轮廓由 `node tools/ros-map-to-vector.js --auto` 自动生成到 map-data.js，
 *    **不要手改轮廓**；改航点就改本文件，改完务必跑
 *    `node tools/gen-waypoints.js --check` 校验（单步 ≤1m / 单条 ≤3.5m / 在图内）。
 */

import mapData from './map-data.js'

/* ------------------------------------------------------------------ *
 * 1. 地图
 *
 * walls 来自车端真实栅格地图的矢量近似（自动生成），只用于**画图**。
 * 本方案**不声称**具备 SLAM / 导航 / 避障能力：路线是预设的，车端只沿线走。
 * ------------------------------------------------------------------ */
export const MAP = {
  name: '实验区（车端真实地图 ' + mapData.MAP_META.name + '）',
  /** 栅格地图的名义尺寸 */
  width: mapData.MAP_META.width,
  height: mapData.MAP_META.height,
  /** 地图坐标系下的原点与分辨率，真车对接时要用 */
  origin: mapData.MAP_META.origin,
  resolution: mapData.MAP_META.resolution,
  /** 实际有墙/障碍的范围，画布按它取景更省地方 */
  bounds: mapData.MAP_META.bounds,
  /** 外墙与固定障碍（自动生成，勿手改） */
  walls: mapData.WALLS,
  /** 外边界缺口（门洞/通道中心点） */
  gaps: mapData.GAPS
}

/* ------------------------------------------------------------------ *
 * 2. 航点
 *
 * 坐标是地图坐标系（米），**与车端 ROS 地图一致**：
 *   x ∈ [-4.51, 12.84]，y ∈ [-3.85, 5.70]
 * 相邻航点间距刻意压在 1 m 以内——这是方案二里"
 * 每条路线的单步距离远小于全局上限（1.0 m）"那条约定。
 *
 * yaw 只作为真车执行时的参考朝向，演示动画的朝向是按**实际行进方向**算的。
 * ------------------------------------------------------------------ */
export const WAYPOINTS = [
  /* --- 入口大厅（左区）：直行 → 90° 左转 --- */
  { id: 'EN01', x: -3.50, y: 3.60, yaw: 0.00, name: '入口起点' },
  { id: 'EN02', x: -2.60, y: 3.60, yaw: 0.00, name: '前台' },
  { id: 'EN03', x: -2.60, y: 4.50, yaw: 1.57, name: '闸机' },
  { id: 'EN04', x: -2.60, y: 5.00, yaw: 1.57, name: '入口终点' },

  /* --- 主通道（中区）：直行 --- */
  { id: 'AI01', x: -1.30, y: 4.20, yaw: 0.00, name: '通道起点' },
  { id: 'AI02', x: -0.40, y: 4.20, yaw: 0.00, name: '通道 A 段' },
  { id: 'AI03', x: 0.50, y: 4.20, yaw: 0.00, name: '通道 B 段' },
  { id: 'AI04', x: 1.30, y: 4.20, yaw: 0.00, name: '通道终点' },

  /* --- 展项区（上右区）：90° 右转 → 直行 --- */
  { id: 'EX01', x: 2.80, y: 1.80, yaw: 0.00, name: '展项起点' },
  { id: 'EX02', x: 2.80, y: 2.70, yaw: 1.57, name: '展台 1' },
  { id: 'EX03', x: 3.70, y: 2.70, yaw: 0.00, name: '展台 3' },
  { id: 'EX04', x: 4.60, y: 2.70, yaw: 0.00, name: '展台 4' },

  /* --- 设备区（下右区）：直行 → 90° 左转 --- */
  { id: 'EQ01', x: 5.00, y: -2.60, yaw: 0.00, name: '配电柜' },
  { id: 'EQ02', x: 5.90, y: -2.60, yaw: 0.00, name: '设备区中段' },
  { id: 'EQ03', x: 6.80, y: -2.60, yaw: 0.00, name: '机柜前' },
  { id: 'EQ04', x: 6.80, y: -1.70, yaw: 1.57, name: '机柜背面' }
]

/* ------------------------------------------------------------------ *
 * 3. 固定路线
 *
 * stops 里的 dwell 是「原地停留看点」的秒数（真车对应 dwell 原语，
 * **不发速度**）。0 表示直接过、不停。
 *
 * 全局路线 ALL_ROUTE 把四条短路线串起来，构成**一条完整的巡检路线**；
 * 四条路线分别落在四块区域里，一轮巡检就是把这四段依次走完。
 * ------------------------------------------------------------------ */
export const ROUTES = {
  route_entrance: {
    name: '入口大厅路线',
    desc: '入口 → 前台 → 闸机',
    stops: [
      { wp: 'EN01', dwell: 0.5 },
      { wp: 'EN02', dwell: 0 },
      { wp: 'EN03', dwell: 0 },
      { wp: 'EN04', dwell: 1.0 }
    ]
  },
  route_aisle: {
    name: '主通道路线',
    desc: '通道 A 段 → B 段',
    stops: [
      { wp: 'AI01', dwell: 0.5 },
      { wp: 'AI02', dwell: 0 },
      { wp: 'AI03', dwell: 0 },
      { wp: 'AI04', dwell: 1.0 }
    ]
  },
  route_exhibit: {
    name: '展项区路线',
    desc: '展台 1 → 展台 4 绕行',
    stops: [
      { wp: 'EX01', dwell: 0.5 },
      { wp: 'EX02', dwell: 0 },
      { wp: 'EX03', dwell: 0 },
      { wp: 'EX04', dwell: 1.0 }
    ]
  },
  route_equipment: {
    name: '设备区路线',
    desc: '配电柜 → 机柜背面',
    stops: [
      { wp: 'EQ01', dwell: 0.5 },
      { wp: 'EQ02', dwell: 0 },
      { wp: 'EQ03', dwell: 0 },
      { wp: 'EQ04', dwell: 1.0 }
    ]
  }
}

/** 整条固定巡检路线（四条短路线依次执行） */
export const ALL_ROUTE = ['route_entrance', 'route_aisle', 'route_exhibit', 'route_equipment']

/* ------------------------------------------------------------------ *
 * 4. 区域登记表：一个区域 = 一条固定路线 = 一台默认车辆
 *
 * 四条路线各自落在自己那块区域里（入口大厅 / 主通道 / 展项区 / 设备区），
 * 所以地图上一眼看得到四条互不重叠的短路线。
 * ------------------------------------------------------------------ */
export const ZONES = [
  { id: 'Z1', name: '入口大厅', route: 'route_entrance', car: 'CAR-1' },
  { id: 'Z2', name: '主通道', route: 'route_aisle', car: 'CAR-2' },
  { id: 'Z3', name: '展项区', route: 'route_exhibit', car: 'CAR-3' },
  { id: 'Z4', name: '设备区', route: 'route_equipment', car: 'CAR-4' }
]

/* ------------------------------------------------------------------ *
 * 5. 车辆表
 *
 * mode 说明本车这一版走哪条通道，界面上如实标出来：
 *   'demo' —— 模拟器内演示：小车标记按航点逐段移动，不碰真车
 *   'ros'  —— 经宿主机桥接到车端 ROS（本版未启用，留接口）
 * ------------------------------------------------------------------ */
export const CARS = [
  { id: 'CAR-1', name: '1 号车', zoneId: 'Z1', zone: '入口大厅', ip: '192.168.1.201', online: true, battery: 88, mode: 'demo' },
  { id: 'CAR-2', name: '2 号车', zoneId: 'Z2', zone: '主通道', ip: '192.168.1.202', online: true, battery: 84, mode: 'demo' },
  { id: 'CAR-3', name: '3 号车', zoneId: 'Z3', zone: '展项区', ip: '192.168.1.203', online: true, battery: 79, mode: 'demo' },
  { id: 'CAR-4', name: '4 号车', zoneId: 'Z4', zone: '设备区', ip: '192.168.1.204', online: true, battery: 91, mode: 'demo' }
]

/* ------------------------------------------------------------------ *
 * 6. 状态字典：任务状态机的五个态（与 Skill / 协议用同一套词）
 * ------------------------------------------------------------------ */
export const STATUS = {
  pending: { text: '待执行', color: '#94A3B8', bg: 'rgba(148,163,184,0.16)' },
  running: { text: '进行中', color: '#4DA3FF', bg: 'rgba(77,163,255,0.16)' },
  done: { text: '已完成', color: '#3DDC84', bg: 'rgba(61,220,132,0.16)' },
  blocked: { text: '阻塞', color: '#FF6B6B', bg: 'rgba(255,107,107,0.16)' },
  cancelled: { text: '已取消', color: '#FBBF24', bg: 'rgba(251,191,36,0.16)' },
  offline: { text: '离线', color: '#FBBF24', bg: 'rgba(251,191,36,0.16)' }
}

/* ------------------------------------------------------------------ *
 * 7. 阈值与限值（与 patrol_zones.json 的 limits 对齐）
 * ------------------------------------------------------------------ */
export const LIMITS = {
  /** 演示推进速度：m/s。真车实测巡检速度是 0.12 m/s，演示用放快，否则一段要 20 秒 */
  demo_speed_mps: 0.8,
  /** 连续多少秒收不到回执判失联 → 阻塞 */
  receipt_timeout_s: 20,
  /** 单任务时限（秒），超时判阻塞 */
  task_deadline_s: 180,
  /** 电量低于此值不派长任务 */
  battery_min: 20,
  /** 单步距离上限（米），与 patrol_zones.json 的 step_distance_max_m 对齐 */
  step_distance_max_m: 1.0
}

/* ------------------------------------------------------------------ *
 * 8. 便捷查询
 * ------------------------------------------------------------------ */
export function waypointById(id) {
  for (let i = 0; i < WAYPOINTS.length; i += 1) {
    if (WAYPOINTS[i].id === id) {
      return WAYPOINTS[i]
    }
  }
  return null
}

export function zoneById(id) {
  for (let i = 0; i < ZONES.length; i += 1) {
    if (ZONES[i].id === id) {
      return ZONES[i]
    }
  }
  return null
}

export function carById(id) {
  for (let i = 0; i < CARS.length; i += 1) {
    if (CARS[i].id === id) {
      return CARS[i]
    }
  }
  return null
}

/** 把一条路线展开成航点对象序列（含每点停留时间） */
export function routePoints(routeId) {
  const r = ROUTES[routeId]
  if (!r) {
    return []
  }
  const out = []
  for (let i = 0; i < r.stops.length; i += 1) {
    const wp = waypointById(r.stops[i].wp)
    if (wp) {
      out.push({
        id: wp.id,
        x: wp.x,
        y: wp.y,
        yaw: wp.yaw,
        name: wp.name,
        dwell: r.stops[i].dwell
      })
    }
  }
  return out
}

/** 一条路线的总长度（米） */
export function routeLength(routeId) {
  const pts = routePoints(routeId)
  let sum = 0
  for (let i = 1; i < pts.length; i += 1) {
    const dx = pts[i].x - pts[i - 1].x
    const dy = pts[i].y - pts[i - 1].y
    sum += Math.sqrt(dx * dx + dy * dy)
  }
  return sum
}

/** 整条巡检路线（四条短路线之和）的总长度 */
export function allRouteLength() {
  let sum = 0
  for (let i = 0; i < ALL_ROUTE.length; i += 1) {
    sum += routeLength(ALL_ROUTE[i])
  }
  return sum
}

export default {
  MAP: MAP,
  WAYPOINTS: WAYPOINTS,
  ROUTES: ROUTES,
  ALL_ROUTE: ALL_ROUTE,
  ZONES: ZONES,
  CARS: CARS,
  STATUS: STATUS,
  LIMITS: LIMITS,
  waypointById: waypointById,
  zoneById: zoneById,
  carById: carById,
  routePoints: routePoints,
  routeLength: routeLength,
  allRouteLength: allRouteLength
}