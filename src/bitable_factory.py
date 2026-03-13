"""Bitable Factory — 模板一键建表引擎。

根据 bitable_templates.py 中的模板定义，在飞书多维表格中自动创建表和字段。
支持：一键建表、新增自定义模板、查询可用模板。
"""

import logging
from typing import Any

from lark_oapi.api.bitable.v1 import (
    CreateAppTableFieldRequest,
    AppTableField,
    AppTableFieldProperty,
)

from src.feishu_bitable import FeishuBitableManager
from src.bitable_templates import (
    BitableTemplate,
    FieldDef,
    TEMPLATE_REGISTRY,
    get_template,
    list_templates,
    list_templates_formatted,
)

logger = logging.getLogger(__name__)

# 飞书 API 字段类型映射
FIELD_TYPE_MAP = {
    1: "Text",
    2: "Number",
    3: "SingleSelect",
    4: "MultiSelect",
    5: "DateTime",
    7: "Checkbox",
    11: "User",
    13: "Phone",
    15: "Url",
    17: "Attachment",
    18: "SingleLink",
    20: "Formula",
    21: "DuplexLink",
    22: "Location",
    23: "GroupChat",
    1001: "CreatedTime",
    1002: "ModifiedTime",
    1003: "CreatedUser",
    1004: "ModifiedUser",
}


class BitableFactory:
    """One-click table creation from templates."""

    def __init__(self, bitable_manager: FeishuBitableManager):
        self.bm = bitable_manager

    def create_from_template(
        self,
        app_token: str,
        template_key: str,
        table_name: str = "",
    ) -> dict | None:
        """Create a table from a template.

        Args:
            app_token: Bitable app token or URL.
            template_key: Template key or Chinese alias.
            table_name: Custom table name (default: template's name).
        Returns: {"table_id": "...", "name": "...", "fields_created": int}
                 or None on failure.
        """
        template = get_template(template_key)
        if not template:
            logger.error(f"Template not found: {template_key}")
            return None

        name = table_name or template.name
        app_token = self.bm.extract_app_token(app_token)

        # 1. Create the table
        table_result = self.bm.create_table(app_token, name)
        if not table_result:
            return None

        table_id = table_result["table_id"]

        # 2. Add fields (skip first — Bitable auto-creates a "多行文本" field)
        fields_created = 0
        existing_fields = self.bm.list_fields(app_token, table_id)
        existing_names = {f["field_name"] for f in existing_fields}

        for field_def in template.fields:
            if field_def.name in existing_names:
                continue

            ok = self._create_field(app_token, table_id, field_def)
            if ok:
                fields_created += 1

        logger.info(
            f"Created table '{name}' ({table_id}) with {fields_created} custom fields"
        )
        return {
            "table_id": table_id,
            "name": name,
            "fields_created": fields_created,
            "template": template_key,
        }

    def create_full_app(
        self,
        template_key: str,
        app_name: str = "",
        folder_token: str = "",
    ) -> dict | None:
        """Create a new Bitable app + table from template.

        Returns: {"app_token": "...", "table_id": "...", "url": "...", "name": "..."}
        """
        template = get_template(template_key)
        if not template:
            logger.error(f"Template not found: {template_key}")
            return None

        name = app_name or template.name

        # 1. Create app
        app_result = self.bm.create_app(name, folder_token)
        if not app_result:
            return None

        # 2. Create table with fields
        table_result = self.create_from_template(
            app_result["app_token"], template_key, name,
        )
        if not table_result:
            return {**app_result, "table_id": None, "name": name}

        return {
            "app_token": app_result["app_token"],
            "url": app_result["url"],
            "table_id": table_result["table_id"],
            "name": name,
            "fields_created": table_result["fields_created"],
        }

    def _create_field(
        self, app_token: str, table_id: str, field_def: FieldDef,
    ) -> bool:
        """Create a single field in a table."""
        try:
            # Build property based on field type
            property_dict = self._build_field_property(field_def)

            field_builder = AppTableField.builder() \
                .field_name(field_def.name) \
                .type(field_def.type)

            if property_dict:
                field_builder = field_builder.property(property_dict)

            req = CreateAppTableFieldRequest.builder() \
                .app_token(app_token) \
                .table_id(table_id) \
                .request_body(field_builder.build()) \
                .build()

            resp = self.bm.client.bitable.v1.app_table_field.create(req)

            if not resp.success():
                logger.warning(
                    f"Failed to create field '{field_def.name}': "
                    f"code={resp.code}, msg={resp.msg}"
                )
                return False

            return True
        except Exception as e:
            logger.error(f"Error creating field '{field_def.name}': {e}")
            return False

    @staticmethod
    def _build_field_property(field_def: FieldDef) -> dict | None:
        """Build field property dict for the API."""
        opts = field_def.options
        if not opts:
            return None

        prop = {}

        # Single/Multi select options
        if field_def.type in (3, 4) and "options" in opts:
            prop["options"] = opts["options"]

        # Number formatter
        if field_def.type == 2 and "formatter" in opts:
            prop["formatter"] = opts["formatter"]

        # Date formatter
        if field_def.type == 5 and "date_formatter" in opts:
            prop["date_formatter"] = opts["date_formatter"]

        return prop if prop else None

    # ── Convenience ──

    @staticmethod
    def list_available() -> list[dict[str, str]]:
        """List all available templates."""
        return list_templates()

    @staticmethod
    def list_available_formatted() -> str:
        """List all templates formatted for chat."""
        return list_templates_formatted()

    def describe_template(self, template_key: str) -> str | None:
        """Get detailed description of a template."""
        template = get_template(template_key)
        if not template:
            return None

        lines = [
            f"📋 **{template.name}**",
            f"_{template.description}_\n",
            f"分类: {template.category}",
            f"字段数: {len(template.fields)}\n",
            "**字段列表:**",
        ]

        type_names = {
            1: "文本", 2: "数字", 3: "单选", 4: "多选", 5: "日期",
            7: "复选框", 11: "人员", 13: "电话", 15: "链接", 17: "附件",
        }

        for f in template.fields:
            type_label = type_names.get(f.type, f"类型{f.type}")
            extra = ""
            if f.type in (3, 4) and "options" in f.options:
                option_names = [o["name"] for o in f.options["options"][:5]]
                extra = f" ({'/'.join(option_names)}{'...' if len(f.options['options']) > 5 else ''})"
            lines.append(f"  • {f.name} [{type_label}]{extra}")

        if template.ai_rules:
            lines.append(f"\n**AI自动处理: {len(template.ai_rules)} 条规则**")
            for rule in template.ai_rules:
                lines.append(f"  🤖 {rule.source_field} → {rule.target_field}")

        if template.tags:
            lines.append(f"\n标签: {', '.join(template.tags)}")

        lines.append(f"\n用法: `/bt create {template_key}` 或 `/bt create {template_key} 自定义表名`")
        return "\n".join(lines)
