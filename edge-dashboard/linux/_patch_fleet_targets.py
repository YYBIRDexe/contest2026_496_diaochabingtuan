#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修「多车指令只动了一台车」—— 三个文件的小补丁。

现象（用户实测）
--------------
说「小车编队，后退0.5米」，**只有 1 号车后退了 0.5 米**。
设备记录里那一轮长这样：

    {"text":"小车编队，后退零点五米。","source":"agent",
     "steps":[{"intent":"backward","params":{"distance_m":0.5}}],   ← 没有 targets
     "step_results":[{"robots":"", "commands":["ros_car.py --car $CAR_IP --robots \"$ROBOTS\" …"]}]}

根因（三处，缺一处都还会犯）
--------------------------
1. **云端提示词没把"编队"算作多车**：agent_slow 的目标车规则只列了
   "所有车/全部/四台车/大家一起"，用户说的是"小车编队"，模型于是（按规则）
   不加 targets。而没有 targets 时 ros_car.py 会退回 $CAR_IP —— 那正是 1 号车。
2. **助手侧没有兜底**：慢路径只信云端给的 targets，云端不给就 ROBOTS 为空。
   用户原话里明明有"编队"这种多车信号，却没人用它。
3. **本地规则把"编队"排在"后退"前面**：`nlp_parse` 里 "编队" 和 "后退" 都是 2 个字，
   按长度排序时 start_formation 更靠前 → 整句被判成"编队实验"（正方形/0.8m/30s），
   完全不是用户的意思。这条现在被 --cloud-first 遮住了，但一旦改回本地优先就会犯。

改法
----
· `voice_button._extract_robots`：把"编队/一起/一块/协同/集体"也算多车；
  并补上 "1号和3号" 这种多车枚举（原来只认第一个车号）。
· `voice_button` 慢路径：云端没给 targets 时，用**用户原话**兜一层。
· `agent_slow` 提示词：把"编队"写进多车清单，并说明 start_formation 只用于队形实验。
· `nlp_parse`：句子里有明确的移动词 + 距离/角度时，按移动处理（编队只表示"一起"）。

用法（在设备 /home/sunrise/voice_pipeline 下执行）：
    python3 _patch_fleet_targets.py            # 打补丁
    python3 _patch_fleet_targets.py --check    # 只看状态
"""
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VB = os.path.join(HERE, "voice_button.py")
AG = os.path.join(HERE, "agent_slow.py")
NP = os.path.join(HERE, "nlp_parse.py")

MARK = "【09-19 多车补丁】"


def _backup(path):
    bak = path + ".bak-before-fleet-" + time.strftime("%m%d_%H%M")
    shutil.copyfile(path, bak)
    return os.path.basename(bak)


def _write(path, src, out):
    try:
        compile(out, path, "exec")          # ast.parse 拦不住编译期错误，用 compile
    except SyntaxError as exc:
        print("  [X] %s 编译不过，已放弃：%s" % (os.path.basename(path), exc))
        return False
    bak = _backup(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)
    print("  [OK] %s 已打补丁（%d -> %d 字节），备份 %s"
          % (os.path.basename(path), len(src), len(out), bak))
    return True


# ---------------------------------------------------------------- voice_button
VB_ANCHOR = '''    # 四台 / 4台 / 四辆车 / 全部 / 所有 / 全体
    if re.search(r"(?:四|4)\\s*(?:台|辆|个)", text) or re.search(r"(?:全部|所有|全体)", text):
        return "1,2,3,4"'''

VB_NEW = '''    # 【09-19 多车补丁】多台枚举："1号和3号" / "2号、4号" -> "1,3" / "2,4"。
    # 原来只认第一个车号，"1号和3号" 会退化成只控 1 号（实测踩到）。
    pair = re.findall(r"([1-4一二两三四])\\s*号", text)
    if len(pair) >= 2:
        return ",".join(sorted({_CAR_DIGIT.get(p, "") for p in pair} - {""}))

    # 四台 / 4台 / 四辆车 / 全部 / 所有 / 全体
    if re.search(r"(?:四|4)\\s*(?:台|辆|个)", text) or re.search(r"(?:全部|所有|全体)", text):
        return "1,2,3,4"
    # 【09-19 多车补丁】"编队 / 一起 / 一块 / 协同 / 集体" 也是"多台一起动"的意思。
    # 实测：用户说「小车编队，后退0.5米」，云端只给了 backward 没给 targets，
    # 这里又没认出"编队" -> ROBOTS 为空 -> ros_car.py 退回 $CAR_IP ->
    # **只有 1 号车动了**。这类"编队+动作"的说法必须落到"全部车"。
    if re.search(r"(?:编队|一起|一块|协同|集体)", text):
        return "1,2,3,4"'''

VB_SLOW_ANCHOR = '''                    elif orig_robots is None:
                        os.environ.pop("ROBOTS", None)
                    else:
                        os.environ["ROBOTS"] = orig_robots'''

VB_SLOW_NEW = '''                    elif orig_robots is None:
                        # 【09-19 多车补丁】云端没给 targets 时，用**用户原话**兜一层：
                        # 说了"编队/四台车/所有车"就说明这是多车动作。
                        # 不兜的话 ROBOTS 为空 -> ros_car 退回默认单台车，
                        # 表现为"四台车编队"只有 1 号车动（实测踩到）。
                        rbs = _extract_robots(text)
                        if rbs:
                            os.environ["ROBOTS"] = rbs
                            print("     目标车（由原话判定）= %s" % rbs)
                        else:
                            os.environ.pop("ROBOTS", None)
                    else:
                        os.environ["ROBOTS"] = orig_robots'''


def patch_voice_button(check_only):
    src = open(VB, encoding="utf-8").read()
    if MARK in src:
        print("  · voice_button.py 已是补丁后版本")
        return 0
    if VB_ANCHOR not in src or VB_SLOW_ANCHOR not in src:
        print("  [X] voice_button.py 找不到锚点（可能被别的改动覆盖了），跳过")
        return 2
    if check_only:
        print("  · voice_button.py 还没打补丁")
        return 1
    out = src.replace(VB_ANCHOR, VB_NEW, 1).replace(VB_SLOW_ANCHOR, VB_SLOW_NEW, 1)
    return 0 if _write(VB, src, out) else 3


# ---------------------------------------------------------------- agent_slow
AG_ANCHOR = '''   "所有车/全部/四台车/大家一起" -> targets:[1,2,3,4]'''

AG_NEW = '''   "所有车/全部/四台车/大家一起" -> targets:[1,2,3,4]
   还有一类说法**没提车号但就是多车**：编队、一起、一块、协同、集体。
   例如「小车编队，后退0.5米」= 所有车一起后退 0.5 米：
       输出：{"intent":"backward","params":{"distance_m":0.5,"targets":[1,2,3,4]},"confidence":0.9}
   注意：「编队+动作」按**动作**理解（backward/forward/... 加 targets），
   start_formation 只用于用户明确要"排队形/做实验"（排成正方形、给间距、跑多久）时。'''

AG_FEWSHOT_ANCHOR = '''输出：{"intent":"start_formation","params":{"formation":"square","spacing_m":0.8,"duration_s":30},"confidence":0.95}'''

AG_FEWSHOT_NEW = '''输出：{"intent":"start_formation","params":{"formation":"square","spacing_m":0.8,"duration_s":30},"confidence":0.95}

用户：小车编队，后退0.5米 / 大家排好队一起后退半米 / 四台车编队往后退0.5米
输出：{"intent":"backward","params":{"distance_m":0.5,"targets":[1,2,3,4]},"confidence":0.9}'''


def patch_agent_slow(check_only):
    src = open(AG, encoding="utf-8").read()
    if MARK in src:
        print("  · agent_slow.py 已是补丁后版本")
        return 0
    if AG_ANCHOR not in src:
        print("  [X] agent_slow.py 找不到目标车规则锚点，跳过")
        return 2
    if check_only:
        print("  · agent_slow.py 还没打补丁")
        return 1
    out = src.replace(AG_ANCHOR, AG_NEW, 1)
    if AG_FEWSHOT_ANCHOR in out:
        out = out.replace(AG_FEWSHOT_ANCHOR, AG_FEWSHOT_NEW, 1)
    # 在文件顶部说明里留个记号，便于 --check 判断
    head = '# ' + MARK + ' 编队/一起 这类「没提车号但就是多车」的说法要带 targets\n'
    out = out.replace('from __future__ import annotations',
                      head + 'from __future__ import annotations', 1)
    return 0 if _write(AG, src, out) else 3


# ---------------------------------------------------------------- nlp_parse
NP_ANCHOR = '''    hits.sort(key=lambda x: -x[2])
    spec = hits[0][0]
    name = spec["name"]'''

NP_NEW = '''    hits.sort(key=lambda x: -x[2])
    spec = hits[0][0]
    # 【09-19 多车补丁】编队 vs 移动的消歧：
    #   「小车编队，后退0.5米」里 "编队" 和 "后退" 都是 2 个字，按长度排序
    #   start_formation 更靠前 -> 整句被判成"编队实验"（正方形/0.8m/30s），
    #   完全不是用户的意思（用户要的是"所有车一起后退 0.5 米"）。
    #   规则：句子里有明确移动词 + 距离/角度时，按移动处理，编队只当"一起"。
    if spec["name"] == "start_formation" \\
            and re.search(r"(?:前进|向前|往前走|往前开|后退|向后|往后|退后)", text) \\
            and re.search(NUM + r"\\s*" + DIST_UNIT, text):
        mv = next((h for h in hits if h[0]["name"] in ("forward", "backward")), None)
        if mv is not None:
            spec = mv[0]
    name = spec["name"]'''


def patch_nlp_parse(check_only):
    src = open(NP, encoding="utf-8").read()
    if MARK in src:
        print("  · nlp_parse.py 已是补丁后版本")
        return 0
    if NP_ANCHOR not in src:
        print("  [X] nlp_parse.py 找不到挑赢家锚点，跳过")
        return 2
    if check_only:
        print("  · nlp_parse.py 还没打补丁")
        return 1
    out = src.replace(NP_ANCHOR, NP_NEW, 1)
    return 0 if _write(NP, src, out) else 3


def main():
    check_only = "--check" in sys.argv
    print("多车目标补丁：")
    rc = [patch_voice_button(check_only), patch_agent_slow(check_only),
          patch_nlp_parse(check_only)]
    if not check_only and 0 in rc:
        print("\n重启语音服务后生效：")
        print("  echo sunrise | sudo -S systemctl restart voice-assistant.service")
    return 0 if all(r in (0, 1) for r in rc) else max(rc)


if __name__ == "__main__":
    sys.exit(main())
