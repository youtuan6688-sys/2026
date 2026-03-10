"""Feishu Bitable (多维表格) Manager — CRUD operations on bitable records.

Enables the bot to:
- Create bitable apps and tables
- Read/list/search records
- Create/update/delete records
- List tables in a bitable app
"""

import logging
import re

import lark_oapi as lark
from lark_oapi.api.bitable.v1 import (
    CreateAppRequest,
    ReqApp,
    CreateAppTableRequest,
    CreateAppTableRequestBody,
    ReqTable,
    ListAppTableRequest,
    CreateAppTableRecordRequest,
    AppTableRecord,
    ListAppTableRecordRequest,
    SearchAppTableRecordRequest,
    SearchAppTableRecordRequestBody,
    UpdateAppTableRecordRequest,
    DeleteAppTableRecordRequest,
    BatchCreateAppTableRecordRequest,
    BatchCreateAppTableRecordRequestBody,
)

from config.settings import Settings

logger = logging.getLogger(__name__)


class FeishuBitableManager:
    """Manage Feishu Bitable (多维表格) operations."""

    def __init__(self, settings: Settings):
        self.client = lark.Client.builder() \
            .app_id(settings.feishu_app_id) \
            .app_secret(settings.feishu_app_secret) \
            .log_level(lark.LogLevel.WARNING) \
            .build()

    @staticmethod
    def extract_app_token(url_or_token: str) -> str:
        """Extract app_token from a Feishu bitable URL or return as-is."""
        match = re.search(r'/base/([A-Za-z0-9]+)', url_or_token)
        if match:
            return match.group(1)
        return url_or_token.strip()

    # ── App & Table Management ──

    def create_app(self, name: str, folder_token: str = "") -> dict | None:
        """Create a new bitable app.

        Returns: {"app_token": "...", "url": "..."} or None.
        """
        builder = ReqApp.builder().name(name)
        if folder_token:
            builder = builder.folder_token(folder_token)

        req = CreateAppRequest.builder() \
            .request_body(builder.build()) \
            .build()
        resp = self.client.bitable.v1.app.create(req)

        if not resp.success():
            logger.error(f"Failed to create bitable: code={resp.code}, msg={resp.msg}")
            return None

        app_token = resp.data.app.app_token
        logger.info(f"Created bitable: {name} -> {app_token}")
        return {
            "app_token": app_token,
            "url": f"https://feishu.cn/base/{app_token}",
        }

    def create_table(self, app_token: str, table_name: str) -> dict | None:
        """Create a new table in a bitable app.

        Returns: {"table_id": "...", "name": "..."} or None.
        """
        req = CreateAppTableRequest.builder() \
            .app_token(app_token) \
            .request_body(
                CreateAppTableRequestBody.builder()
                .table(ReqTable.builder().name(table_name).build())
                .build()
            ).build()
        resp = self.client.bitable.v1.app_table.create(req)

        if not resp.success():
            logger.error(f"Failed to create table: code={resp.code}, msg={resp.msg}")
            return None

        table_id = resp.data.table_id
        logger.info(f"Created table: {table_name} -> {table_id}")
        return {"table_id": table_id, "name": table_name}

    def list_tables(self, app_token: str) -> list[dict]:
        """List all tables in a bitable app.

        Returns: [{"table_id": "...", "name": "...", "revision": ...}]
        """
        app_token = self.extract_app_token(app_token)
        req = ListAppTableRequest.builder() \
            .app_token(app_token) \
            .build()
        resp = self.client.bitable.v1.app_table.list(req)

        if not resp.success():
            logger.error(f"Failed to list tables: code={resp.code}, msg={resp.msg}")
            return []

        tables = []
        for t in (resp.data.items or []):
            tables.append({
                "table_id": t.table_id,
                "name": t.name,
                "revision": getattr(t, 'revision', 0),
            })
        logger.info(f"Listed {len(tables)} tables in {app_token}")
        return tables

    # ── Record Operations ──

    def create_record(self, app_token: str, table_id: str,
                      fields: dict) -> dict | None:
        """Create a single record.

        Returns: {"record_id": "..."} or None.
        """
        app_token = self.extract_app_token(app_token)
        req = CreateAppTableRecordRequest.builder() \
            .app_token(app_token) \
            .table_id(table_id) \
            .request_body(
                AppTableRecord.builder().fields(fields).build()
            ).build()
        resp = self.client.bitable.v1.app_table_record.create(req)

        if not resp.success():
            logger.error(f"Failed to create record: code={resp.code}, msg={resp.msg}")
            return None

        record_id = resp.data.record.record_id
        logger.info(f"Created record {record_id} in {table_id}")
        return {"record_id": record_id}

    def batch_create_records(self, app_token: str, table_id: str,
                             records: list[dict]) -> list[str]:
        """Batch create records (max 500 per call).

        Args:
            records: list of field dicts, e.g. [{"Name": "Alice", "Age": 30}]
        Returns: list of created record_ids.
        """
        app_token = self.extract_app_token(app_token)
        record_objs = [
            AppTableRecord.builder().fields(r).build()
            for r in records[:500]
        ]

        req = BatchCreateAppTableRecordRequest.builder() \
            .app_token(app_token) \
            .table_id(table_id) \
            .request_body(
                BatchCreateAppTableRecordRequestBody.builder()
                .records(record_objs)
                .build()
            ).build()
        resp = self.client.bitable.v1.app_table_record.batch_create(req)

        if not resp.success():
            logger.error(f"Failed to batch create: code={resp.code}, msg={resp.msg}")
            return []

        ids = [r.record_id for r in (resp.data.records or [])]
        logger.info(f"Batch created {len(ids)} records in {table_id}")
        return ids

    def list_records(self, app_token: str, table_id: str,
                     page_size: int = 20,
                     page_token: str = "") -> dict:
        """List records in a table.

        Returns: {"records": [...], "has_more": bool, "page_token": "..."}
        """
        app_token = self.extract_app_token(app_token)
        builder = ListAppTableRecordRequest.builder() \
            .app_token(app_token) \
            .table_id(table_id) \
            .page_size(page_size)
        if page_token:
            builder = builder.page_token(page_token)

        resp = self.client.bitable.v1.app_table_record.list(builder.build())

        if not resp.success():
            logger.error(f"Failed to list records: code={resp.code}, msg={resp.msg}")
            return {"records": [], "has_more": False, "page_token": ""}

        records = []
        for r in (resp.data.items or []):
            records.append({
                "record_id": r.record_id,
                "fields": r.fields or {},
            })

        return {
            "records": records,
            "has_more": resp.data.has_more or False,
            "page_token": resp.data.page_token or "",
        }

    def update_record(self, app_token: str, table_id: str,
                      record_id: str, fields: dict) -> bool:
        """Update a single record's fields."""
        app_token = self.extract_app_token(app_token)
        req = UpdateAppTableRecordRequest.builder() \
            .app_token(app_token) \
            .table_id(table_id) \
            .record_id(record_id) \
            .request_body(
                AppTableRecord.builder().fields(fields).build()
            ).build()
        resp = self.client.bitable.v1.app_table_record.update(req)

        if not resp.success():
            logger.error(f"Failed to update record: code={resp.code}, msg={resp.msg}")
            return False

        logger.info(f"Updated record {record_id}")
        return True

    def delete_record(self, app_token: str, table_id: str,
                      record_id: str) -> bool:
        """Delete a single record."""
        app_token = self.extract_app_token(app_token)
        req = DeleteAppTableRecordRequest.builder() \
            .app_token(app_token) \
            .table_id(table_id) \
            .record_id(record_id) \
            .build()
        resp = self.client.bitable.v1.app_table_record.delete(req)

        if not resp.success():
            logger.error(f"Failed to delete record: code={resp.code}, msg={resp.msg}")
            return False

        logger.info(f"Deleted record {record_id}")
        return True

    # ── Formatting ──

    def format_records(self, records: list[dict], max_records: int = 10) -> str:
        """Format records for display in chat."""
        if not records:
            return "(无记录)"

        lines = []
        for i, r in enumerate(records[:max_records]):
            fields = r.get("fields", {})
            field_parts = []
            for k, v in fields.items():
                # Handle different field value types
                if isinstance(v, list):
                    # Multi-select, people, etc.
                    display = ", ".join(
                        item.get("text", item.get("name", str(item)))
                        if isinstance(item, dict) else str(item)
                        for item in v
                    )
                elif isinstance(v, dict):
                    display = v.get("text", v.get("name", str(v)))
                else:
                    display = str(v)
                field_parts.append(f"{k}: {display}")
            lines.append(f"{i+1}. {' | '.join(field_parts)}")

        result = "\n".join(lines)
        if len(records) > max_records:
            result += f"\n... 还有 {len(records) - max_records} 条记录"
        return result
