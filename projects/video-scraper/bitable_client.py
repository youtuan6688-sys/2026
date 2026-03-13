"""飞书 Bitable 读写客户端 — 用于任务轮询和结果写入"""

import json
import logging
import os
import time
from typing import Any

import requests

from scraper_config import BITABLE_APP_TOKEN, TASK_TABLE_ID, RESULT_TABLE_ID, BREAKDOWN_TABLE_ID, LARK_API_BASE

logger = logging.getLogger(__name__)

_token_cache: dict[str, Any] = {}


def _get_tenant_token() -> str:
    """获取 tenant_access_token（缓存 1.5 小时）"""
    now = time.time()
    if _token_cache.get("token") and now < _token_cache.get("expires_at", 0):
        return _token_cache["token"]

    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        raise RuntimeError("FEISHU_APP_ID / FEISHU_APP_SECRET not set")

    resp = requests.post(
        f"{LARK_API_BASE}/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=10,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Failed to get token: {data}")

    token = data["tenant_access_token"]
    _token_cache["token"] = token
    _token_cache["expires_at"] = now + 5400  # 1.5h
    return token


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_get_tenant_token()}",
        "Content-Type": "application/json",
    }


def fetch_pending_tasks() -> list[dict]:
    """获取状态为「待抓取」的任务，按优先级排序"""
    url = f"{LARK_API_BASE}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{TASK_TABLE_ID}/records/search"
    body = {
        "filter": {
            "conjunction": "and",
            "conditions": [
                {
                    "field_name": "状态",
                    "operator": "is",
                    "value": ["待抓取"],
                }
            ],
        },
        "sort": [
            {"field_name": "优先级", "desc": False},  # 高 < 中 < 低
        ],
    }
    resp = requests.post(url, headers=_headers(), json=body, timeout=15)
    data = resp.json()
    if data.get("code") != 0:
        logger.error(f"Fetch tasks failed: {data.get('msg')}")
        return []

    items = data.get("data", {}).get("items", [])
    tasks = []
    for item in items:
        fields = item.get("fields", {})
        # 时间范围：从 SingleSelect 读取（如 "7天" → "7d"）
        time_raw = _text_value(fields.get("时间范围", ""))
        time_filter = ""
        if "7" in time_raw:
            time_filter = "7d"
        elif "30" in time_raw or "月" in time_raw:
            time_filter = "30d"
        elif "90" in time_raw or "季" in time_raw:
            time_filter = "90d"

        tasks.append({
            "record_id": item["record_id"],
            "keyword": _text_value(fields.get("关键词", "")),
            "count": int(fields.get("数量", 5)),
            "priority": _text_value(fields.get("优先级", "中")),
            "time_filter": time_filter,
        })
    return tasks


def update_task_status(record_id: str, status: str, extra_fields: dict | None = None) -> None:
    """更新任务状态"""
    url = f"{LARK_API_BASE}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{TASK_TABLE_ID}/records/{record_id}"
    fields: dict[str, Any] = {"状态": status}
    if extra_fields:
        fields.update(extra_fields)
    resp = requests.put(url, headers=_headers(), json={"fields": fields}, timeout=10)
    if resp.json().get("code") != 0:
        logger.error(f"Update task failed: {resp.json().get('msg')}")


def write_result(result: dict) -> str | None:
    """写入一条视频分析结果，返回 record_id"""
    url = f"{LARK_API_BASE}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{RESULT_TABLE_ID}/records"
    resp = requests.post(url, headers=_headers(), json={"fields": result}, timeout=15)
    data = resp.json()
    if data.get("code") != 0:
        logger.error(f"Write result failed: {data.get('msg')}")
        return None
    return data.get("data", {}).get("record", {}).get("record_id")


def write_breakdown_rows(rows: list[dict]) -> int:
    """批量写入逐秒拆解行，返回成功写入的数量"""
    url = f"{LARK_API_BASE}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BREAKDOWN_TABLE_ID}/records/batch_create"
    records = [{"fields": row} for row in rows]
    # Bitable 批量写入上限 500 条
    written = 0
    for i in range(0, len(records), 500):
        batch = records[i:i+500]
        resp = requests.post(url, headers=_headers(), json={"records": batch}, timeout=30)
        data = resp.json()
        if data.get("code") != 0:
            logger.error(f"Write breakdown batch failed: {data.get('msg')}")
        else:
            written += len(batch)
    return written


_owner_shared = False


def ensure_owner_access(owner_open_id: str = "") -> None:
    """确保用户对 Bitable 有 full_access 权限，并尝试转移所有权（仅执行一次）"""
    global _owner_shared
    if _owner_shared:
        return

    if not owner_open_id:
        owner_open_id = os.environ.get("FEISHU_ADMIN_OPEN_ID", "ou_4a18a2e35a5b04262a24f41731046d15")

    # Step 1: 授权 full_access
    url = f"{LARK_API_BASE}/drive/v1/permissions/{BITABLE_APP_TOKEN}/members"
    body = {
        "member_type": "openid",
        "member_id": owner_open_id,
        "perm": "full_access",
    }
    params = {"type": "bitable"}
    try:
        resp = requests.post(url, headers=_headers(), json=body, params=params, timeout=10)
        data = resp.json()
        if data.get("code") == 0:
            logger.info(f"Granted full_access to {owner_open_id}")
        else:
            logger.warning(f"Permission grant response: {data.get('code')} - {data.get('msg')}")
    except Exception as e:
        logger.error(f"Failed to grant owner access: {e}")

    # Step 2: 转移所有权给用户
    _transfer_ownership(owner_open_id)
    _owner_shared = True


def _transfer_ownership(new_owner_open_id: str) -> None:
    """将 Bitable 所有权转移给指定用户"""
    url = f"{LARK_API_BASE}/drive/v1/permissions/{BITABLE_APP_TOKEN}/members/transfer_owner"
    body = {
        "member_type": "openid",
        "member_id": new_owner_open_id,
    }
    params = {"type": "bitable", "need_notification": "true"}
    try:
        resp = requests.post(url, headers=_headers(), json=body, params=params, timeout=10)
        data = resp.json()
        if data.get("code") == 0:
            logger.info(f"Ownership transferred to {new_owner_open_id}")
        else:
            # 常见错误：已经是 owner / 无权转移
            logger.warning(f"Ownership transfer: {data.get('code')} - {data.get('msg')}")
    except Exception as e:
        logger.error(f"Ownership transfer failed: {e}")


def _text_value(val: Any) -> str:
    """从 Bitable 字段值提取纯文本"""
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        # rich text format: [{"text": "...", "type": "text"}]
        return "".join(item.get("text", "") for item in val if isinstance(item, dict))
    return str(val) if val else ""
