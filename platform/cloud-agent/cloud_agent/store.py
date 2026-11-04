"""Thread-safe proposal store with optional JSON persistence.

A proposal is a *plan*, not an execution command.  In v1 there is no motion
executor, so the execution state is immutable: ``not_executed``.  Approval only
records that a human confirmed the plan version.
"""

import json
import os
import threading
from pathlib import Path

from .errors import StoreError
from .util import isoformat, new_id, truncate_text, utc_now

EXECUTION_REASON = (
    "首版没有运动执行器。批准只表示计划被确认，不会下发车辆、不会改变车辆状态，"
    "也不等于已执行。"
)


class ProposalStore(object):
    def __init__(self, path=None, now_fn=None, max_entries=200):
        self.path = Path(path) if path else None
        self._now = now_fn or utc_now
        self.max_entries = max(10, int(max_entries))
        self._lock = threading.RLock()
        self._proposals = []
        self.load_warning = ""
        self._load()

    def _load(self):
        if self.path is None or not self.path.is_file():
            return
        try:
            with open(str(self.path), "r", encoding="utf-8") as handle:
                document = json.load(handle)
            proposals = document.get("proposals") if isinstance(document, dict) else None
            if not isinstance(proposals, list):
                raise ValueError("顶层缺少 proposals 数组")
            valid = []
            for item in proposals:
                if isinstance(item, dict) and item.get("proposal_id") and item.get("status"):
                    valid.append(item)
            with self._lock:
                self._proposals = valid[-self.max_entries :]
        except (OSError, ValueError) as exc:
            self.load_warning = "提案文件无法读取，已保留原文件并从未空状态启动: %s" % (exc,)
            try:
                corrupt = self.path.with_name(
                    self.path.name + ".corrupt-" + self._now().strftime("%Y%m%d%H%M%S")
                )
                os.replace(str(self.path), str(corrupt))
            except OSError:
                pass

    def _save_locked(self):
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.path.with_name(self.path.name + ".tmp")
            payload = {
                "schema_version": "1.0",
                "saved_at": isoformat(self._now()),
                "proposals": self._proposals,
            }
            with open(str(temp_path), "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(str(temp_path), str(self.path))
            try:
                os.chmod(str(self.path), 0o600)
            except OSError:
                pass
        except OSError as exc:
            raise StoreError(
                "提案持久化失败：%s" % (exc.strerror or exc),
                code="proposal_persistence_failed",
                http_status=500,
            )

    def create_from_validation(self, validation, source="api", rationale=None):
        if not isinstance(validation, dict) or not validation.get("ok"):
            raise StoreError(
                "只有通过校验的任务才能生成计划。",
                code="mission_not_validated",
                http_status=422,
                details={"validation": validation},
            )
        if not validation.get("route") or not validation.get("checks"):
            raise StoreError("校验结果缺少路线或检查项。", code="invalid_validation", http_status=500)

        now = self._now()
        proposal = {
            "schema_version": "1.0",
            "proposal_id": new_id("prop"),
            "plan_version": 1,
            "status": "pending_confirmation",
            "created_at": isoformat(now),
            "source": source if source in ("agent_tool", "api") else "api",
            "rationale": truncate_text(rationale, 500) if rationale else "",
            "mission": {
                "route": dict(validation["route"]),
                "checks": [dict(item) for item in validation["checks"]],
                "robot": dict(validation["robot"]) if validation.get("robot") else None,
                "scheduled_for": validation.get("scheduled_for"),
                "validation_id": validation["validation_id"],
                "validated_at": validation["validated_at"],
                "warnings": [dict(item) for item in validation.get("warnings", [])],
            },
            "approval": {
                "required": True,
                "state": "pending",
                "binds_plan_version": 1,
                "binding": {
                    "validation_id": validation["validation_id"],
                    "route_id": validation["route"]["id"],
                },
                "decided_at": None,
                "decided_by": None,
                "note": "",
            },
            "execution": {
                "state": "not_executed",
                "executor": "none_v1",
                "executor_available": False,
                "reason": EXECUTION_REASON,
                "last_attempt_at": None,
                "last_result": None,
            },
            "registry": dict(validation.get("registry") or {}),
        }
        with self._lock:
            self._proposals.append(proposal)
            if len(self._proposals) > self.max_entries:
                self._proposals = self._proposals[-self.max_entries :]
            self._save_locked()
        return {"ok": True, "proposal": proposal, "proposal_id": proposal["proposal_id"]}

    def list(self, limit=50):
        try:
            limit = max(1, min(200, int(limit)))
        except (TypeError, ValueError):
            limit = 50
        with self._lock:
            items = list(reversed(self._proposals))[:limit]
            return {
                "ok": True,
                "count": len(items),
                "total": len(self._proposals),
                "proposals": [dict(item) for item in items],
            }

    def get(self, proposal_id):
        with self._lock:
            for proposal in self._proposals:
                if proposal["proposal_id"] == proposal_id:
                    return {"ok": True, "proposal": dict(proposal)}
        raise StoreError(
            "没有找到提案 %r。" % proposal_id,
            code="proposal_not_found",
            http_status=404,
        )

    def decide(self, proposal_id, decision, actor=None, note=None):
        if decision not in ("approve", "reject"):
            raise StoreError(
                "decision 必须是 approve 或 reject。",
                code="invalid_decision",
                http_status=400,
            )
        actor_name = truncate_text(actor, 80).strip() if actor else "operator"
        note_text = truncate_text(note, 500).strip() if note else ""
        with self._lock:
            proposal = None
            for item in self._proposals:
                if item["proposal_id"] == proposal_id:
                    proposal = item
                    break
            if proposal is None:
                raise StoreError(
                    "没有找到提案 %r。" % proposal_id,
                    code="proposal_not_found",
                    http_status=404,
                )
            approval = proposal.get("approval") or {}
            if approval.get("state") != "pending":
                raise StoreError(
                    "提案已作出决定，不能重复批准或驳回。",
                    code="proposal_already_decided",
                    http_status=409,
                    details={"state": approval.get("state")},
                )
            now = isoformat(self._now())
            approval["state"] = "approved" if decision == "approve" else "rejected"
            approval["decided_at"] = now
            approval["decided_by"] = actor_name
            approval["note"] = note_text
            proposal["approval"] = approval
            proposal["status"] = "confirmed_not_executed" if decision == "approve" else "rejected"
            # Execution stays exactly as it was: no executor in v1.  Be
            # defensive about a proposal file written by an older version.
            execution = proposal.get("execution")
            if not isinstance(execution, dict):
                execution = {
                    "state": "not_executed",
                    "executor": "none_v1",
                    "executor_available": False,
                    "reason": EXECUTION_REASON,
                    "last_attempt_at": None,
                    "last_result": None,
                }
                proposal["execution"] = execution
            execution["state"] = "not_executed"
            self._save_locked()
            return {"ok": True, "proposal": dict(proposal)}
