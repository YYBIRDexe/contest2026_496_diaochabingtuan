"""End-to-end ledger demo: real C task ledger -> network dispatch -> fleet simulator.

Three rounds, each with its own ledger directory so the evidence is independent:
1. three robots accept, run and complete distinct tasks;
2. the vehicle link drops mid-flight, the board keeps the task pending and a
   later dispatch succeeds without duplicate execution;
3. an IMMEDIATE risk event during execution stops the running robot and blocks
   any sibling task on the same tag.

Everything here runs the host build of the C ledger against the loopback
simulator. It is NOT board evidence and performs no motion.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from host.robot_simulator import Fleet, make_server  # noqa: E402

CLI = os.environ.get('SPINE_CLI', str(Path(__file__).resolve().parent.parent / 'build' / 'spine-cli'))
STEPS = []


def cli(*args, expect=0):
    proc = subprocess.run([CLI, *args], capture_output=True, text=True)
    payload = json.loads(proc.stdout) if proc.stdout.strip() else None
    STEPS.append({'argv': list(args), 'returncode': proc.returncode, 'stdout': proc.stdout.strip()[:400]})
    if proc.returncode != expect:
        raise SystemExit('unexpected rc %d != %d for %s: %s' % (proc.returncode, expect, args, proc.stdout))
    return payload


def write_plan(path, plan_id, version, tasks):
    path.write_text(json.dumps({'schema': 'spine-plan-v1', 'plan_id': plan_id,
                                'version': version, 'tasks': tasks}), encoding='utf-8')
    return str(path)


def report(endpoint, robot, task, revision, state, sequence):
    import urllib.request
    body = json.dumps({'schema': 'spine-robot-sim-v1', 'mode': 'simulation',
                       'command_id': 'report-%s-%s-%d' % (task, state, sequence),
                       'robot_id': robot, 'task_id': task, 'revision': revision,
                       'action': 'REPORT', 'state': state, 'sequence': sequence}).encode()
    request = urllib.request.Request('http://%s/v1/commands' % endpoint, data=body,
                                     headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=5) as response:
        return json.load(response)


def state(endpoint):
    with urlopen('http://%s/v1/state' % endpoint, timeout=5) as response:
        return {row['task_id']: row for row in json.load(response)['tasks']}


def ingest(path, tag, values, revision, event_id):
    payload = {'event_id': event_id, 'robot_id': 'S1', 'tag_id': tag, 'revision': revision,
               'policy_version': 'spine-v2', 'mode': 'replay', 'fresh': True,
               'factors': dict(zip(('consequence', 'urgency', 'exposure', 'spread'), values))}
    path.write_text(json.dumps(payload), encoding='utf-8')
    return str(path)


def run_round_basic(root, endpoint, fleet):
    ledger = root / 'round1'
    ledger.mkdir()
    plan = write_plan(root / 'r1.json', 'demo-r1', 1, [
        {'task_id': 'T1-1', 'tag_id': 'D1', 'robot_id': 'S1', 'revision': 1},
        {'task_id': 'T1-2', 'tag_id': 'D3', 'robot_id': 'S2', 'revision': 1},
        {'task_id': 'T1-3', 'tag_id': 'D6', 'robot_id': 'S3', 'revision': 1},
    ])
    planned = cli('--task-plan', plan, str(ledger))
    dispatched = cli('--task-dispatch', str(ledger), endpoint)
    accepted = {row['task_id']: row['state'] for row in fleet.snapshot()['tasks']}
    for task, robot in (('T1-1', 'S1'), ('T1-2', 'S2'), ('T1-3', 'S3')):
        report(endpoint, robot, task, 1, 'RUNNING', 1)
        cli('--task-poll', str(ledger), endpoint)
        report(endpoint, robot, task, 1, 'COMPLETED', 2)
        cli('--task-poll', str(ledger), endpoint)
    view = cli('--task-view', str(ledger))
    local = {row['task_id']: row['state'] for row in view['tasks']}
    remote = {k: v['state'] for k, v in state(endpoint).items()}
    return {'name': 'round1_three_robots', 'plan_status': planned['status'],
            'dispatch_status': dispatched['status'],
            'dispatched': [row['status'] for row in dispatched['tasks']],
            'simulator_accepted': accepted, 'local_final': local,
            'simulator_final': remote,
            'passed': all(v == 'COMPLETED' for v in local.values()) and
                      all(v == 'COMPLETED' for v in remote.values())}


def run_round_offline(root, endpoint_holder, fleet_ref):
    ledger = root / 'round2'
    ledger.mkdir()
    plan = write_plan(root / 'r2.json', 'demo-r2', 1,
                      [{'task_id': 'T2-1', 'tag_id': 'D1', 'robot_id': 'S1', 'revision': 1}])
    cli('--task-plan', plan, str(ledger))
    endpoint, server = endpoint_holder['endpoint'], endpoint_holder['server']
    server.shutdown()
    server.server_close()
    endpoint_holder['thread'].join()
    dropped = cli('--task-dispatch', str(ledger), endpoint, expect=4)
    pending = cli('--task-view', str(ledger))['tasks'][0]['state']
    orphan = [row for row in fleet_ref['fleet'].snapshot()['tasks'] if row['task_id'] == 'T2-1']
    server = make_server(fleet_ref['fleet'])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    recovered_endpoint = '127.0.0.1:%d' % server.server_port
    endpoint_holder.update(endpoint=recovered_endpoint, server=server, thread=thread)
    again = cli('--task-dispatch', str(ledger), recovered_endpoint)
    report(recovered_endpoint, 'S1', 'T2-1', 1, 'RUNNING', 1)
    cli('--task-poll', str(ledger), recovered_endpoint)
    report(recovered_endpoint, 'S1', 'T2-1', 1, 'COMPLETED', 2)
    cli('--task-poll', str(ledger), recovered_endpoint)
    final = cli('--task-view', str(ledger))['tasks'][0]['state']
    return {'name': 'round2_offline_recovery', 'offline_dispatch': dropped['status'],
            'status_while_offline': [row['status'] for row in dropped['tasks']],
            'local_state_after_drop': pending, 'vehicle_rows_after_drop': orphan,
            'recovered_dispatch': again['status'], 'local_final': final,
            'passed': dropped['status'] == 'PARTIAL_NETWORK_ERROR' and pending == 'DISPATCHING'
                      and not orphan and final == 'COMPLETED'}


def run_round_risk(root, endpoint, fleet):
    ledger = root / 'round3'
    ledger.mkdir()
    plan = write_plan(root / 'r3.json', 'demo-r3', 1, [
        {'task_id': 'T3-1', 'tag_id': 'D1', 'robot_id': 'S1', 'revision': 1},
        {'task_id': 'T3-3', 'tag_id': 'D6', 'robot_id': 'S3', 'revision': 1},
    ])
    cli('--task-plan', plan, str(ledger))
    cli('--task-dispatch', str(ledger), endpoint)
    for task, robot in (('T3-1', 'S1'), ('T3-3', 'S3')):
        report(endpoint, robot, task, 1, 'RUNNING', 1)
    cli('--task-poll', str(ledger), endpoint)
    event = ingest(root / 'risk.json', 'D6', (5, 5, 4, 3), 2, 'demo-risk-1')
    stored = cli('--ingest', event, str(ledger))
    sweep = cli('--task-dispatch', str(ledger), endpoint)
    sibling_plan = write_plan(root / 'r3b.json', 'demo-r3', 2,
                              [{'task_id': 'T3-9', 'tag_id': 'D6', 'robot_id': 'S2', 'revision': 1}])
    cli('--task-plan', sibling_plan, str(ledger))
    blocked = cli('--task-dispatch', str(ledger), endpoint)
    view = {row['task_id']: row['state'] for row in cli('--task-view', str(ledger))['tasks']}
    fleet_state = {k: v['state'] for k, v in state(endpoint).items()}
    return {'name': 'round3_risk_linkage', 'event_status': stored['status'],
            'event_score': stored.get('score'), 'event_decision': stored.get('decision'),
            'sweep_status': sweep['status'], 'stops': sweep['stops'],
            'blocked_status': [row['status'] for row in blocked['tasks']],
            'local_state': view, 'simulator_state': fleet_state,
            'passed': stored.get('decision') == 'IMMEDIATE_HUMAN'
                      and sweep['status'] == 'RISK_STOPPED'
                      and sweep['stops'][0]['status'] == 'STOP_CONFIRMED'
                      and view.get('T3-9') == 'PENDING'
                      and fleet_state.get('T3-3') == 'STOP_CONFIRMED'}


def main(output=None):
    started = time.strftime('%Y-%m-%dT%H:%M:%S%z')
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    fleet = Fleet(root / 'fleet.db')
    server = make_server(fleet)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    holder = {'endpoint': '127.0.0.1:%d' % server.server_port, 'server': server, 'thread': thread}
    rounds = []
    try:
        rounds.append(run_round_basic(root, holder['endpoint'], fleet))
        rounds.append(run_round_offline(root, holder, {'fleet': fleet}))
        rounds.append(run_round_risk(root, holder['endpoint'], fleet))
    finally:
        holder['server'].shutdown()
        holder['server'].server_close()
        holder['thread'].join()
        temp.cleanup()
    report_doc = {'passed': all(item['passed'] for item in rounds),
                  'source': 'HOST_SPINE_CLI', 'board_verified': False,
                  'physical_execution': False, 'motion': False,
                  'started': started, 'finished': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                  'cli': CLI, 'rounds': rounds, 'steps': STEPS}
    text = json.dumps(report_doc, ensure_ascii=False, indent=2)
    if output:
        Path(output).write_text(text, encoding='utf-8')
    print(json.dumps({'passed': report_doc['passed'],
                      'rounds': [{'name': r['name'], 'passed': r['passed']} for r in rounds]},
                     ensure_ascii=False))
    return 0 if report_doc['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else None))
