"""Feishu Bitable (多维表格) Manager — CRUD operations on bitable records.

Enables the bot to:
- Create bitable apps and tables
- Read/list/search records
- Create/update/delete records
- List tables in a bitable app
"""

import json
import logging
import re

import httpx
import lark_oapi as lark
from lark_oapi.api.bitable.v1 import (
    CreateAppRequest,
    ReqApp,
    CreateAppTableRequest,
    CreateAppTableRequestBody,
    ReqTable,
    ListAppTableRequest,
    ListAppTableFieldRequest,
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

    def list_fields(self, app_token: str, table_id: str) -> list[dict]:
        """List all fields (columns) in a table.

        Returns: [{"field_id": "...", "field_name": "...", "type": int, "ui_type": "..."}]
        Field types: 1=Text, 2=Number, 3=SingleSelect, 4=MultiSelect, 5=DateTime,
                     7=Checkbox, 11=User, 13=Phone, 15=Url, 17=Attachment,
                     18=Link, 20=Formula, 21=DuplexLink, 22=Location, 23=GroupChat,
                     1001=CreatedTime, 1002=ModifiedTime, 1003=CreatedUser, 1004=ModifiedUser
        """
        app_token = self.extract_app_token(app_token)
        req = ListAppTableFieldRequest.builder() \
            .app_token(app_token) \
            .table_id(table_id) \
            .page_size(100) \
            .build()
        resp = self.client.bitable.v1.app_table_field.list(req)

        if not resp.success():
            logger.error(f"Failed to list fields: code={resp.code}, msg={resp.msg}")
            return []

        type_names = {
            1: "多行文本", 2: "数字", 3: "单选", 4: "多选", 5: "日期",
            7: "复选框", 11: "人员", 13: "电话", 15: "超链接", 17: "附件",
            18: "单向关联", 20: "公式", 21: "双向关联", 22: "地理位置",
            23: "群组", 1001: "创建时间", 1002: "最后更新时间",
            1003: "创建人", 1004: "修改人", 1005: "自动编号",
        }

        fields = []
        for f in (resp.data.items or []):
            fields.append({
                "field_id": f.field_id,
                "field_name": f.field_name,
                "type": f.type,
                "type_name": type_names.get(f.type, f"未知({f.type})"),
                "ui_type": getattr(f, 'ui_type', ''),
            })
        logger.info(f"Listed {len(fields)} fields in {table_id}")
        return fields

    def format_fields(self, fields: list[dict]) -> str:
        """Format field list for display in chat."""
        if not fields:
            return "(无字段)"
        lines = []
        for f in fields:
            lines.append(f"• {f['field_name']} ({f['type_name']})")
        return "\n".join(lines)

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

    def search_records(self, app_token: str, table_id: str,
                       field_name: str, operator: str, value: list[str],
                       page_size: int = 20) -> dict:
        """Search records with filter conditions.

        Args:
            field_name: Name of the field to filter on.
            operator: One of 'is', 'isNot', 'contains', 'doesNotContain',
                      'isEmpty', 'isNotEmpty', 'isGreater', 'isLess'.
            value: Filter value(s) as list of strings.
        Returns: {"records": [...], "has_more": bool, "total": int}
        """
        app_token = self.extract_app_token(app_token)

        filter_body = {
            "conjunction": "and",
            "conditions": [{
                "field_name": field_name,
                "operator": operator,
                "value": value,
            }],
        }

        req = SearchAppTableRecordRequest.builder() \
            .app_token(app_token) \
            .table_id(table_id) \
            .page_size(page_size) \
            .request_body(
                SearchAppTableRecordRequestBody.builder()
                .filter(filter_body)
                .build()
            ).build()
        resp = self.client.bitable.v1.app_table_record.search(req)

        if not resp.success():
            logger.error(f"Failed to search records: code={resp.code}, msg={resp.msg}")
            return {"records": [], "has_more": False, "total": 0}

        records = []
        for r in (resp.data.items or []):
            records.append({
                "record_id": r.record_id,
                "fields": r.fields or {},
            })

        return {
            "records": records,
            "has_more": resp.data.has_more or False,
            "total": getattr(resp.data, 'total', len(records)),
        }

    def search_records_multi(self, app_token: str, table_id: str,
                             conditions: list[dict],
                             conjunction: str = "and",
                             page_size: int = 20) -> dict:
        """Search records with multiple filter conditions.

        Args:
            conditions: [{"field_name": "...", "operator": "...", "value": ["..."]}]
            conjunction: "and" or "or"
        Returns: {"records": [...], "has_more": bool, "total": int}
        """
        app_token = self.extract_app_token(app_token)

        filter_body = {
            "conjunction": conjunction,
            "conditions": conditions,
        }

        req = SearchAppTableRecordRequest.builder() \
            .app_token(app_token) \
            .table_id(table_id) \
            .page_size(page_size) \
            .request_body(
                SearchAppTableRecordRequestBody.builder()
                .filter(filter_body)
                .build()
            ).build()
        resp = self.client.bitable.v1.app_table_record.search(req)

        if not resp.success():
            logger.error(f"Failed to search records: code={resp.code}, msg={resp.msg}")
            return {"records": [], "has_more": False, "total": 0}

        records = []
        for r in (resp.data.items or []):
            records.append({
                "record_id": r.record_id,
                "fields": r.fields or {},
            })

        return {
            "records": records,
            "has_more": resp.data.has_more or False,
            "total": getattr(resp.data, 'total', len(records)),
        }

    # ── AI Processing ──

    def ai_process_record(self, app_token: str, table_id: str,
                          record_id: str, source_field: str,
                          target_fields: dict[str, str],
                          ai_base_url: str = "",
                          ai_api_key: str = "",
                          ai_model: str = "") -> bool:
        """Read a record's source field, run AI prompts, write results back.

        Args:
            app_token: Bitable app token.
            table_id: Table ID.
            record_id: Record to process.
            source_field: Field name containing source content.
            target_fields: {field_name: prompt_template} — each prompt gets
                           the source content via {content} placeholder,
                           AI result is written to the field_name.
            ai_base_url: AI API base URL (defaults to settings).
            ai_api_key: AI API key (defaults to settings).
            ai_model: AI model name (defaults to settings).
        Returns: True if all fields processed successfully.
        """
        from config.settings import settings as _settings

        base_url = ai_base_url or _settings.ai_base_url
        api_key = ai_api_key or _settings.ai_api_key
        model = ai_model or _settings.ai_model

        # 1. Read the record
        app_token = self.extract_app_token(app_token)
        result = self.search_records(
            app_token, table_id, "record_id", "is", [record_id],
        )
        # Fallback: list and find
        if not result["records"]:
            all_records = self.list_records(app_token, table_id, page_size=500)
            matching = [
                r for r in all_records["records"]
                if r["record_id"] == record_id
            ]
            if not matching:
                logger.error(f"Record {record_id} not found")
                return False
            record = matching[0]
        else:
            record = result["records"][0]

        source_content = record["fields"].get(source_field, "")
        if isinstance(source_content, list):
            # Multi-value field: join text representations
            source_content = "\n".join(
                item.get("text", str(item)) if isinstance(item, dict) else str(item)
                for item in source_content
            )
        elif isinstance(source_content, dict):
            source_content = source_content.get("text", str(source_content))
        else:
            source_content = str(source_content)

        if not source_content.strip():
            logger.warning(f"Source field '{source_field}' is empty for record {record_id}")
            return False

        # 2. Process each target field with AI
        updates = {}
        all_ok = True

        for field_name, prompt_template in target_fields.items():
            prompt = prompt_template.replace("{content}", source_content)
            try:
                resp = httpx.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 2000,
                        "temperature": 0.3,
                    },
                    timeout=60,
                )
                resp.raise_for_status()
                ai_result = resp.json()["choices"][0]["message"]["content"].strip()
                updates[field_name] = ai_result
                logger.info(f"AI processed {field_name} for record {record_id}: {len(ai_result)} chars")
            except Exception as e:
                logger.error(f"AI processing failed for {field_name}: {e}")
                all_ok = False

        # 3. Write results back
        if updates:
            success = self.update_record(app_token, table_id, record_id, updates)
            if not success:
                all_ok = False

        return all_ok

    def ai_process_batch(self, app_token: str, table_id: str,
                         source_field: str, target_fields: dict[str, str],
                         filter_field: str = "", filter_value: str = "",
                         max_records: int = 50) -> dict:
        """Batch AI-process records that haven't been processed yet.

        Args:
            filter_field: Optional field to filter unprocessed records
                          (e.g., check if target field is empty).
            filter_value: Value to match (use empty string for isEmpty check).
            max_records: Max records to process per batch.
        Returns: {"processed": int, "failed": int, "skipped": int}
        """
        app_token = self.extract_app_token(app_token)

        # Get records to process
        if filter_field:
            result = self.search_records(
                app_token, table_id,
                filter_field, "isEmpty", [],
                page_size=max_records,
            )
            records = result["records"]
        else:
            result = self.list_records(app_token, table_id, page_size=max_records)
            records = result["records"]

        stats = {"processed": 0, "failed": 0, "skipped": 0}

        for record in records:
            record_id = record["record_id"]
            source = record["fields"].get(source_field, "")
            if not source:
                stats["skipped"] += 1
                continue

            ok = self.ai_process_record(
                app_token, table_id, record_id,
                source_field, target_fields,
            )
            if ok:
                stats["processed"] += 1
            else:
                stats["failed"] += 1

        logger.info(f"Batch AI processing: {stats}")
        return stats

    # ── Batch Operations ──

    def batch_update_records(self, app_token: str, table_id: str,
                              updates: list[dict]) -> dict:
        """Batch update records.

        Args:
            updates: [{"record_id": "...", "fields": {...}}]
        Returns: {"success": int, "failed": int}
        """
        from lark_oapi.api.bitable.v1 import (
            BatchUpdateAppTableRecordRequest,
            BatchUpdateAppTableRecordRequestBody,
        )
        app_token = self.extract_app_token(app_token)
        stats = {"success": 0, "failed": 0}

        # Process in chunks of 500
        for i in range(0, len(updates), 500):
            chunk = updates[i:i + 500]
            record_objs = [
                AppTableRecord.builder()
                .record_id(u["record_id"])
                .fields(u["fields"])
                .build()
                for u in chunk
            ]
            req = BatchUpdateAppTableRecordRequest.builder() \
                .app_token(app_token) \
                .table_id(table_id) \
                .request_body(
                    BatchUpdateAppTableRecordRequestBody.builder()
                    .records(record_objs)
                    .build()
                ).build()
            resp = self.client.bitable.v1.app_table_record.batch_update(req)

            if resp.success():
                stats["success"] += len(chunk)
            else:
                logger.error(f"Batch update failed: code={resp.code}, msg={resp.msg}")
                stats["failed"] += len(chunk)

        logger.info(f"Batch update: {stats}")
        return stats

    def batch_delete_records(self, app_token: str, table_id: str,
                              record_ids: list[str]) -> dict:
        """Batch delete records.

        Returns: {"success": int, "failed": int}
        """
        from lark_oapi.api.bitable.v1 import (
            BatchDeleteAppTableRecordRequest,
            BatchDeleteAppTableRecordRequestBody,
        )
        app_token = self.extract_app_token(app_token)
        stats = {"success": 0, "failed": 0}

        for i in range(0, len(record_ids), 500):
            chunk = record_ids[i:i + 500]
            req = BatchDeleteAppTableRecordRequest.builder() \
                .app_token(app_token) \
                .table_id(table_id) \
                .request_body(
                    BatchDeleteAppTableRecordRequestBody.builder()
                    .records(chunk)
                    .build()
                ).build()
            resp = self.client.bitable.v1.app_table_record.batch_delete(req)

            if resp.success():
                stats["success"] += len(chunk)
            else:
                logger.error(f"Batch delete failed: code={resp.code}, msg={resp.msg}")
                stats["failed"] += len(chunk)

        logger.info(f"Batch delete: {stats}")
        return stats

    # ── Advanced Query ──

    def list_all_records(self, app_token: str, table_id: str,
                          max_pages: int = 10) -> list[dict]:
        """Fetch all records with automatic pagination.

        Returns: list of {"record_id": "...", "fields": {...}}
        """
        all_records = []
        page_token = ""

        for _ in range(max_pages):
            result = self.list_records(
                app_token, table_id,
                page_size=500, page_token=page_token,
            )
            all_records.extend(result["records"])
            if not result["has_more"]:
                break
            page_token = result["page_token"]

        logger.info(f"Fetched all: {len(all_records)} records from {table_id}")
        return all_records

    def search_records_advanced(self, app_token: str, table_id: str,
                                 conditions: list[dict],
                                 conjunction: str = "and",
                                 sort: list[dict] | None = None,
                                 field_names: list[str] | None = None,
                                 page_size: int = 50) -> dict:
        """Advanced search with sort and field selection.

        Args:
            conditions: [{"field_name": "...", "operator": "...", "value": ["..."]}]
            conjunction: "and" or "or"
            sort: [{"field_name": "...", "order": "asc"|"desc"}]
            field_names: specific fields to return (None = all)
        Returns: {"records": [...], "has_more": bool, "total": int}
        """
        app_token = self.extract_app_token(app_token)

        body_builder = SearchAppTableRecordRequestBody.builder()

        if conditions:
            body_builder = body_builder.filter({
                "conjunction": conjunction,
                "conditions": conditions,
            })

        if sort:
            body_builder = body_builder.sort(sort)

        if field_names:
            body_builder = body_builder.field_names(field_names)

        req = SearchAppTableRecordRequest.builder() \
            .app_token(app_token) \
            .table_id(table_id) \
            .page_size(page_size) \
            .request_body(body_builder.build()) \
            .build()
        resp = self.client.bitable.v1.app_table_record.search(req)

        if not resp.success():
            logger.error(f"Advanced search failed: code={resp.code}, msg={resp.msg}")
            return {"records": [], "has_more": False, "total": 0}

        records = [
            {"record_id": r.record_id, "fields": r.fields or {}}
            for r in (resp.data.items or [])
        ]
        return {
            "records": records,
            "has_more": resp.data.has_more or False,
            "total": getattr(resp.data, 'total', len(records)),
        }

    # ── Data Export ──

    def export_to_markdown(self, app_token: str, table_id: str,
                            field_names: list[str] | None = None,
                            max_records: int = 100) -> str:
        """Export table data as Markdown table.

        Args:
            field_names: columns to include (None = all)
            max_records: max rows to export
        Returns: Markdown table string
        """
        records = self.list_all_records(app_token, table_id)[:max_records]
        if not records:
            return "(无数据)"

        # Determine columns
        if field_names:
            cols = field_names
        else:
            # Collect all field names from records
            col_set: dict[str, None] = {}
            for r in records:
                for k in r["fields"]:
                    col_set[k] = None
            cols = list(col_set.keys())

        # Build table
        header = "| " + " | ".join(cols) + " |"
        separator = "| " + " | ".join("---" for _ in cols) + " |"
        rows = []
        for r in records:
            cells = []
            for col in cols:
                val = r["fields"].get(col, "")
                cells.append(self._format_cell(val))
            rows.append("| " + " | ".join(cells) + " |")

        return "\n".join([header, separator] + rows)

    def export_to_csv(self, app_token: str, table_id: str,
                       field_names: list[str] | None = None,
                       max_records: int = 500) -> str:
        """Export table data as CSV string.

        Returns: CSV-formatted string (comma-separated, with header)
        """
        import csv
        import io

        records = self.list_all_records(app_token, table_id)[:max_records]
        if not records:
            return ""

        if field_names:
            cols = field_names
        else:
            col_set: dict[str, None] = {}
            for r in records:
                for k in r["fields"]:
                    col_set[k] = None
            cols = list(col_set.keys())

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(cols)

        for r in records:
            row = [self._format_cell(r["fields"].get(col, "")) for col in cols]
            writer.writerow(row)

        return output.getvalue()

    def get_table_stats(self, app_token: str, table_id: str) -> dict:
        """Get table statistics: record count, field count, field types.

        Returns: {"record_count": int, "field_count": int, "fields": [...]}
        """
        fields = self.list_fields(app_token, table_id)
        # Count records (use search with no filter to get total)
        result = self.list_records(app_token, table_id, page_size=1)
        # Rough count via pagination
        all_records = self.list_all_records(app_token, table_id)
        return {
            "record_count": len(all_records),
            "field_count": len(fields),
            "fields": fields,
        }

    @staticmethod
    def _format_cell(val) -> str:
        """Format a field value for export."""
        if val is None or val == "":
            return ""
        if isinstance(val, list):
            return ", ".join(
                item.get("text", item.get("name", str(item)))
                if isinstance(item, dict) else str(item)
                for item in val
            )
        if isinstance(val, dict):
            return val.get("text", val.get("link", val.get("name", str(val))))
        return str(val).replace("\n", " ").replace("|", "\\|")

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
