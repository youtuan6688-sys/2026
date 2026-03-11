"""Feishu Document Manager — read, create, update, and share online documents.

Enables the bot to:
- Read content from Feishu online docs (by URL or doc_id)
- Create new documents with structured content
- Update existing documents
- Share documents with specified users
- Use Feishu docs as a collaboration layer between bot and team members
"""

import json
import logging
import re

import lark_oapi as lark
from lark_oapi.api.docx.v1 import (
    Block,
    Text,
    TextElement,
    TextRun,
    Image as DocImage,
    CreateDocumentRequest,
    CreateDocumentRequestBody,
    GetDocumentRequest,
    ListDocumentBlockRequest,
    CreateDocumentBlockChildrenRequest,
    CreateDocumentBlockChildrenRequestBody,
)
from lark_oapi.api.drive.v1 import (
    CreatePermissionMemberRequest,
    BaseMember,
    ListFileRequest,
    DownloadMediaRequest,
)

from pathlib import Path

from config.settings import Settings

# Image placeholder pattern: [IMAGE:file_token]
_IMAGE_MARKER_RE = re.compile(r'\[IMAGE:([^\]]+)\]')

logger = logging.getLogger(__name__)


class FeishuDocManager:
    """Manage Feishu online documents for the bot."""

    # Admin user to auto-share all created documents with
    ADMIN_OPEN_ID = "ou_4a18a2e35a5b04262a24f41731046d15"

    def __init__(self, settings: Settings):
        self.client = lark.Client.builder() \
            .app_id(settings.feishu_app_id) \
            .app_secret(settings.feishu_app_secret) \
            .log_level(lark.LogLevel.WARNING) \
            .build()

    @staticmethod
    def extract_doc_id(url_or_id: str) -> str:
        """Extract document ID from a Feishu URL or return as-is if already an ID."""
        # Match patterns like /docx/XXXXX or /docs/XXXXX
        match = re.search(r'/(?:docx|docs|wiki)/([A-Za-z0-9]+)', url_or_id)
        if match:
            return match.group(1)
        # Assume it's already a doc_id
        return url_or_id.strip()

    def create_document(self, title: str, folder_token: str = "") -> dict | None:
        """Create a new empty document.

        Returns: {"doc_id": "...", "url": "..."} or None on failure.
        """
        builder = CreateDocumentRequestBody.builder().title(title)
        if folder_token:
            builder = builder.folder_token(folder_token)
        body = builder.build()

        req = CreateDocumentRequest.builder().request_body(body).build()
        resp = self.client.docx.v1.document.create(req)

        if not resp.success():
            logger.error(f"Failed to create doc: code={resp.code}, msg={resp.msg}")
            return None

        doc_id = resp.data.document.document_id
        logger.info(f"Created document: {title} -> {doc_id}")

        # Auto-share with admin so they can edit/manage
        self.share_document(doc_id, self.ADMIN_OPEN_ID,
                            member_type="openid", perm="full_access")

        return {
            "doc_id": doc_id,
            "url": f"https://feishu.cn/docx/{doc_id}",
        }

    def read_document(self, url_or_id: str) -> dict | None:
        """Read a document's title and text content.

        Returns: {"title": "...", "content": "...", "doc_id": "..."} or None.
        """
        doc_id = self.extract_doc_id(url_or_id)

        # Get document metadata
        get_req = GetDocumentRequest.builder().document_id(doc_id).build()
        get_resp = self.client.docx.v1.document.get(get_req)

        if not get_resp.success():
            # Common: 99003 = no permission, 91002 = not found
            logger.error(f"Failed to get doc {doc_id}: code={get_resp.code}, msg={get_resp.msg}")
            if get_resp.code in (99003, 91002, 95009):
                logger.warning(
                    f"Permission denied for doc {doc_id}. "
                    f"User needs to share this doc with the bot app."
                )
            return None

        title = get_resp.data.document.title

        # List all blocks to extract text
        list_req = ListDocumentBlockRequest.builder() \
            .document_id(doc_id) \
            .page_size(500) \
            .build()
        list_resp = self.client.docx.v1.document_block.list(list_req)

        if not list_resp.success():
            logger.error(f"Failed to list blocks for {doc_id}: {list_resp.msg}")
            return {"title": title, "content": "", "doc_id": doc_id}

        # Build block_id → block map for table cell lookups
        all_blocks = list_resp.data.items or []
        block_map = {}
        table_child_ids = set()
        for block in all_blocks:
            bid = getattr(block, "block_id", None)
            if bid:
                block_map[bid] = block
            # Mark table/table_cell children so we skip them in the top-level loop
            if block.block_type in (18, 19):  # table or table_cell
                for child_id in (block.children or []):
                    table_child_ids.add(child_id)

        # Extract text from top-level blocks (skip blocks nested inside tables)
        text_parts = []
        for block in all_blocks:
            bid = getattr(block, "block_id", None)
            if bid and bid in table_child_ids:
                continue  # handled by table extraction
            block_text = self._extract_block_text(block, block_map=block_map)
            if block_text:
                text_parts.append(block_text)

        content = "\n".join(text_parts)
        logger.info(f"Read document: {title} ({len(content)} chars)")
        return {"title": title, "content": content, "doc_id": doc_id}

    def write_content(self, url_or_id: str, text: str) -> bool:
        """Append text content to an existing document.

        Splits text into paragraphs and adds them as Block objects.
        Supports [IMAGE:file_token] markers — these are converted to
        image blocks so images are preserved during document rewrites.
        """
        doc_id = self.extract_doc_id(url_or_id)

        paragraphs = [p for p in text.strip().split("\n") if p.strip()]
        if not paragraphs:
            return True

        # Build Block objects in batches of 50 (API limit)
        batch_size = 50
        total_written = 0

        for batch_start in range(0, len(paragraphs), batch_size):
            batch = paragraphs[batch_start:batch_start + batch_size]
            blocks = []
            for para in batch:
                block = self._para_to_block(para)
                blocks.append(block)

            body = CreateDocumentBlockChildrenRequestBody.builder() \
                .children(blocks) \
                .index(-1) \
                .build()

            req = CreateDocumentBlockChildrenRequest.builder() \
                .document_id(doc_id) \
                .block_id(doc_id) \
                .request_body(body) \
                .build()

            resp = self.client.docx.v1.document_block_children.create(req)

            if not resp.success():
                logger.error(
                    f"Failed to write to doc {doc_id} "
                    f"(batch {batch_start // batch_size + 1}): "
                    f"code={resp.code}, msg={resp.msg}"
                )
                return False

            total_written += len(blocks)

        logger.info(f"Wrote {total_written} blocks to document {doc_id}")
        return True

    @staticmethod
    def _para_to_block(para: str) -> Block:
        """Convert a paragraph string to a Block, handling image markers."""
        # Image marker: [IMAGE:file_token]
        m = _IMAGE_MARKER_RE.fullmatch(para.strip())
        if m:
            file_token = m.group(1)
            return Block.builder() \
                .block_type(27) \
                .image(
                    DocImage.builder().token(file_token).build()
                ).build()

        # Default: text paragraph
        return Block.builder() \
            .block_type(2) \
            .text(
                Text.builder().elements([
                    TextElement.builder().text_run(
                        TextRun.builder()
                        .content(para[:2000])
                        .build()
                    ).build()
                ]).build()
            ).build()

    def create_and_write(self, title: str, content: str,
                         folder_token: str = "") -> dict | None:
        """Create a new document and write content to it.

        Returns: {"doc_id": "...", "url": "..."} or None.
        """
        result = self.create_document(title, folder_token=folder_token)
        if not result:
            return None

        if content:
            self.write_content(result["doc_id"], content)

        return result

    def share_document(self, url_or_id: str, member_id: str,
                       member_type: str = "openid",
                       perm: str = "full_access") -> bool:
        """Share a document with a user.

        Args:
            url_or_id: Document URL or ID
            member_id: User's open_id, email, or user_id
            member_type: "openid", "email", "userid", or "chat_id"
            perm: "full_access", "edit", or "view"
        """
        doc_id = self.extract_doc_id(url_or_id)

        # Detect doc type from URL pattern
        doc_type = "docx"
        if isinstance(url_or_id, str) and "/wiki/" in url_or_id:
            doc_type = "wiki"

        member = BaseMember.builder() \
            .member_type(member_type) \
            .member_id(member_id) \
            .perm(perm) \
            .build()

        req = CreatePermissionMemberRequest.builder() \
            .token(doc_id) \
            .type(doc_type) \
            .request_body(member) \
            .build()

        resp = self.client.drive.v1.permission_member.create(req)

        if not resp.success():
            logger.error(f"Failed to share doc {doc_id}: code={resp.code}, msg={resp.msg}")
            return False

        logger.info(f"Shared document {doc_id} with {member_id} ({perm})")
        return True

    def list_folder(self, folder_token: str = "",
                    page_size: int = 50) -> list[dict]:
        """List files in a folder (or root if no token).

        Returns list of {"name", "type", "token", "url"} dicts.
        """
        req = ListFileRequest.builder() \
            .folder_token(folder_token) \
            .page_size(page_size) \
            .build()
        resp = self.client.drive.v1.file.list(req)

        if not resp.success():
            logger.error(f"Failed to list folder: code={resp.code}, msg={resp.msg}")
            return []

        results = []
        for f in (resp.data.files or []):
            file_type = f.type or "unknown"
            token = f.token or ""
            url = f"https://feishu.cn/{file_type}/{token}" if file_type in ("docx", "sheet", "bitable") else ""
            results.append({
                "name": f.name or "(unnamed)",
                "type": file_type,
                "token": token,
                "url": url,
            })

        logger.info(f"Listed {len(results)} files in folder {folder_token or 'root'}")
        return results

    def download_image(self, file_token: str, save_dir: str = "/tmp") -> str | None:
        """Download an image from a Feishu document by its file_token.

        Returns the local file path, or None on failure.
        Used for Strategy B: on-demand image analysis by Claude.
        """
        req = DownloadMediaRequest.builder() \
            .file_token(file_token) \
            .build()
        resp = self.client.drive.v1.media.download(req)

        if not resp.success():
            logger.error(f"Failed to download image {file_token}: "
                         f"code={resp.code}, msg={resp.msg}")
            return None

        save_path = Path(save_dir) / f"{file_token}.png"
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(resp.file.read())
        logger.info(f"Downloaded image {file_token} → {save_path}")
        return str(save_path)

    def _extract_table(self, table_block, block_map: dict) -> str:
        """Extract a table block as a markdown table.

        Feishu tables are nested: table → table_cells → text blocks.
        The cells list in table.property gives row_size × column_size layout.
        """
        tbl = getattr(table_block, "table", None)
        prop = getattr(tbl, "property", None) if tbl else None
        if not prop:
            return ""

        rows = getattr(prop, "row_size", 0) or 0
        cols = getattr(prop, "column_size", 0) or 0
        if rows == 0 or cols == 0:
            return ""

        # Get ordered list of cell block IDs
        cell_ids = tbl.cells or []
        # cells is a flat list in row-major order: [r0c0, r0c1, ..., r1c0, ...]

        def _cell_text(cell_id: str) -> str:
            cell_block = block_map.get(cell_id)
            if not cell_block:
                return ""
            # Table cell's children are text/paragraph blocks
            parts = []
            for child_id in (cell_block.children or []):
                child = block_map.get(child_id)
                if child:
                    txt = self._extract_block_text(child)
                    if txt:
                        parts.append(txt)
            return " ".join(parts).replace("|", "\\|")

        # Build markdown table
        md_rows = []
        for r in range(rows):
            row_cells = []
            for c in range(cols):
                idx = r * cols + c
                text = _cell_text(cell_ids[idx]) if idx < len(cell_ids) else ""
                row_cells.append(text)
            md_rows.append("| " + " | ".join(row_cells) + " |")

            # Add header separator after first row
            if r == 0:
                md_rows.append("| " + " | ".join(["---"] * cols) + " |")

        return "\n".join(md_rows)

    @staticmethod
    def _extract_elements(obj) -> str:
        """Extract text from a block's elements list."""
        if not obj or not hasattr(obj, 'elements'):
            return ""
        parts = []
        for elem in (obj.elements or []):
            if elem.text_run:
                parts.append(elem.text_run.content or "")
        return "".join(parts)

    def _extract_block_text(self, block, block_map: dict | None = None) -> str:
        """Extract text content from a document block."""
        block_type = block.block_type
        extract = self._extract_elements

        def _safe_attr(name: str):
            return getattr(block, name, None)

        # Table (type 18) — reconstruct as markdown table
        if block_type == 18 and block_map:
            return self._extract_table(block, block_map)

        # Text/Paragraph (type 2)
        if block_type == 2:
            return extract(_safe_attr("text"))

        # Heading 1-9 (types 3-11)
        if 3 <= block_type <= 11:
            level = block_type - 2
            txt = extract(_safe_attr(f"heading{level}"))
            if txt:
                return f"{'#' * level} {txt}"
            return ""

        # Bullet list (type 12)
        if block_type == 12:
            return f"- {extract(_safe_attr('bullet'))}"

        # Ordered list (type 13)
        if block_type == 13:
            return f"1. {extract(_safe_attr('ordered'))}"

        # Code block (type 14)
        if block_type == 14:
            return f"```\n{extract(_safe_attr('code'))}\n```"

        # Quote (type 15)
        if block_type == 15:
            return f"> {extract(_safe_attr('quote'))}"

        # Todo (type 17)
        if block_type == 17:
            return f"- [ ] {extract(_safe_attr('todo'))}"

        # Divider (type 22)
        if block_type == 22:
            return "---"

        # Callout (type 26)
        if block_type == 26:
            return extract(_safe_attr("callout"))

        # Image (type 27)
        if block_type == 27:
            img = _safe_attr("image")
            if img:
                token = getattr(img, "token", "") or ""
                return f"[IMAGE:{token}]" if token else "[IMAGE]"
            return "[IMAGE]"

        # File (type 28)
        if block_type == 28:
            f = _safe_attr("file")
            if f:
                name = getattr(f, "name", "") or ""
                return f"[FILE:{name}]" if name else "[FILE]"

        return ""
