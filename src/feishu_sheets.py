"""Feishu Spreadsheet (电子表格) Manager — create, read, write cells.

v3 SDK handles metadata (create spreadsheet, list sheets).
v2 REST API handles cell read/write (not wrapped by SDK, uses client.request()).
"""

import json
import logging
import re

import lark_oapi as lark
from lark_oapi.api.sheets.v3 import (
    CreateSpreadsheetRequest,
    Spreadsheet,
    GetSpreadsheetRequest,
    QuerySpreadsheetSheetRequest,
)
from lark_oapi.core.model import RawRequest
from lark_oapi.core.enum import HttpMethod, AccessTokenType

from config.settings import Settings

logger = logging.getLogger(__name__)


class FeishuSheetsManager:
    """Manage Feishu Spreadsheets (电子表格)."""

    def __init__(self, settings: Settings):
        self.client = lark.Client.builder() \
            .app_id(settings.feishu_app_id) \
            .app_secret(settings.feishu_app_secret) \
            .log_level(lark.LogLevel.WARNING) \
            .build()

    @staticmethod
    def extract_token(url_or_token: str) -> str:
        """Extract spreadsheet token from URL or return as-is."""
        match = re.search(r'/sheets/([A-Za-z0-9]+)', url_or_token)
        if match:
            return match.group(1)
        return url_or_token.strip()

    # ── Spreadsheet Management (v3 SDK) ──

    def create_spreadsheet(self, title: str,
                           folder_token: str = "") -> dict | None:
        """Create a new spreadsheet.

        Returns: {"token": "...", "url": "..."} or None.
        """
        builder = Spreadsheet.builder().title(title)
        if folder_token:
            builder = builder.folder_token(folder_token)

        req = CreateSpreadsheetRequest.builder() \
            .request_body(builder.build()) \
            .build()
        resp = self.client.sheets.v3.spreadsheet.create(req)

        if not resp.success():
            logger.error(f"Failed to create spreadsheet: code={resp.code}, msg={resp.msg}")
            return None

        token = resp.data.spreadsheet.spreadsheet_token
        logger.info(f"Created spreadsheet: {title} -> {token}")
        return {
            "token": token,
            "url": f"https://feishu.cn/sheets/{token}",
        }

    def get_spreadsheet_info(self, url_or_token: str) -> dict | None:
        """Get spreadsheet metadata.

        Returns: {"token": "...", "title": "..."} or None.
        """
        token = self.extract_token(url_or_token)
        req = GetSpreadsheetRequest.builder() \
            .spreadsheet_token(token) \
            .build()
        resp = self.client.sheets.v3.spreadsheet.get(req)

        if not resp.success():
            logger.error(f"Failed to get spreadsheet: code={resp.code}, msg={resp.msg}")
            return None

        return {
            "token": token,
            "title": resp.data.spreadsheet.title,
        }

    def list_sheets(self, url_or_token: str) -> list[dict]:
        """List all sheets (worksheets) in a spreadsheet.

        Returns: [{"sheet_id": "...", "title": "...", "index": ...}]
        """
        token = self.extract_token(url_or_token)
        req = QuerySpreadsheetSheetRequest.builder() \
            .spreadsheet_token(token) \
            .build()
        resp = self.client.sheets.v3.spreadsheet_sheet.query(req)

        if not resp.success():
            logger.error(f"Failed to list sheets: code={resp.code}, msg={resp.msg}")
            return []

        sheets = []
        for s in (resp.data.sheets or []):
            sheets.append({
                "sheet_id": s.sheet_id,
                "title": s.title,
                "index": getattr(s, 'index', 0),
                "row_count": getattr(s, 'grid_properties', None) and s.grid_properties.row_count or 0,
                "col_count": getattr(s, 'grid_properties', None) and s.grid_properties.column_count or 0,
            })
        logger.info(f"Listed {len(sheets)} sheets in {token}")
        return sheets

    # ── Cell Read/Write (v2 REST API) ──

    def read_range(self, url_or_token: str, range_str: str) -> list[list] | None:
        """Read cell values from a range.

        Args:
            range_str: e.g. "Sheet1!A1:C10" or "{sheet_id}!A1:C10"
        Returns: 2D list of values, or None on error.
        """
        token = self.extract_token(url_or_token)
        req = RawRequest.builder() \
            .http_method(HttpMethod.GET) \
            .uri(f"/open-apis/sheets/v2/spreadsheets/{token}/values/{range_str}") \
            .token_types({AccessTokenType.TENANT}) \
            .build()

        resp = self.client.request(req)

        if not resp.success:
            logger.error(f"Failed to read range: {resp.code} {resp.msg}")
            return None

        try:
            data = json.loads(resp.raw.content)
            values = data.get("data", {}).get("valueRange", {}).get("values", [])
            logger.info(f"Read {len(values)} rows from {token}/{range_str}")
            return values
        except Exception as e:
            logger.error(f"Failed to parse read response: {e}")
            return None

    def write_range(self, url_or_token: str, range_str: str,
                    values: list[list]) -> bool:
        """Write cell values to a range.

        Args:
            range_str: e.g. "Sheet1!A1:C2"
            values: 2D list, e.g. [["Name", "Age"], ["Alice", 30]]
        """
        token = self.extract_token(url_or_token)
        body = {
            "valueRange": {
                "range": range_str,
                "values": values,
            }
        }

        req = RawRequest.builder() \
            .http_method(HttpMethod.PUT) \
            .uri(f"/open-apis/sheets/v2/spreadsheets/{token}/values") \
            .token_types({AccessTokenType.TENANT}) \
            .body(body) \
            .build()

        resp = self.client.request(req)

        if not resp.success:
            logger.error(f"Failed to write range: {resp.code} {resp.msg}")
            return False

        logger.info(f"Wrote {len(values)} rows to {token}/{range_str}")
        return True

    def append_rows(self, url_or_token: str, range_str: str,
                    values: list[list]) -> bool:
        """Append rows after existing data.

        Args:
            range_str: e.g. "Sheet1!A:C" (columns to append to)
            values: 2D list of rows to append
        """
        token = self.extract_token(url_or_token)
        body = {
            "valueRange": {
                "range": range_str,
                "values": values,
            }
        }

        req = RawRequest.builder() \
            .http_method(HttpMethod.POST) \
            .uri(f"/open-apis/sheets/v2/spreadsheets/{token}/values_append") \
            .token_types({AccessTokenType.TENANT}) \
            .body(body) \
            .build()

        resp = self.client.request(req)

        if not resp.success:
            logger.error(f"Failed to append rows: {resp.code} {resp.msg}")
            return False

        logger.info(f"Appended {len(values)} rows to {token}/{range_str}")
        return True

    # ── Formatting ──

    def format_cells(self, values: list[list], max_rows: int = 15) -> str:
        """Format cell data for chat display."""
        if not values:
            return "(空表格)"

        lines = []
        for i, row in enumerate(values[:max_rows]):
            cells = [str(c) if c is not None else "" for c in row]
            if i == 0:
                # Header row
                lines.append(" | ".join(cells))
                lines.append("-" * min(60, len(lines[0])))
            else:
                lines.append(" | ".join(cells))

        result = "\n".join(lines)
        if len(values) > max_rows:
            result += f"\n... 还有 {len(values) - max_rows} 行"
        return result
