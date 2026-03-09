import re
import time
import logging

import requests
from bs4 import BeautifulSoup
from readability import Document

from src.parsers.base import BaseParser, DEFAULT_HEADERS
from src.models.content import ParsedContent

logger = logging.getLogger(__name__)

_SKIP_DOMAINS = {"pic.twitter.com"}


class TwitterParser(BaseParser):
    """Parser for X/Twitter posts.

    Strategy:
    1. Use Jina Reader (r.jina.ai) for full rendered content (best for articles)
    2. Supplement with vxTwitter API for metadata (author, likes, images)
    3. Fall back to oembed API
    """

    def parse(self, url: str) -> ParsedContent:
        tweet_id = self._extract_tweet_id(url)
        if not tweet_id:
            return self._fallback(url)

        # Get metadata from vxTwitter (author, likes, images)
        vx_data = self._fetch_vxtwitter_safe(tweet_id)

        # Get full content via Jina Reader (renders the page, gets article text)
        jina_content = self._fetch_jina(url)

        if jina_content:
            return self._build_from_jina(url, tweet_id, jina_content, vx_data)

        # If Jina fails, use vxTwitter data alone
        if vx_data:
            return self._build_from_vxtwitter(url, tweet_id, vx_data)

        # Last resort: oembed
        try:
            return self._parse_oembed(url)
        except Exception as e:
            logger.warning(f"Oembed also failed: {e}")

        return self._fallback(url)

    def _extract_tweet_id(self, url: str) -> str | None:
        match = re.search(r'/status/(\d+)', url)
        return match.group(1) if match else None

    def _fetch_jina(self, url: str) -> str | None:
        """Use Jina Reader to get rendered page content as text."""
        try:
            resp = requests.get(
                f"https://r.jina.ai/{url}",
                headers={"Accept": "text/plain", "X-Return-Format": "text"},
                timeout=30,
            )
            if resp.status_code == 200 and len(resp.text) > 100:
                # Clean up: remove login prompts and navigation noise
                lines = resp.text.split("\n")
                clean_lines = []
                skip_patterns = [
                    "Don't miss what's happening",
                    "People on X are the first to know",
                    "Log in", "Sign up", "See new posts",
                ]
                for line in lines:
                    stripped = line.strip()
                    if any(p in stripped for p in skip_patterns):
                        continue
                    clean_lines.append(line)
                return "\n".join(clean_lines).strip()
        except Exception as e:
            logger.warning(f"Jina Reader failed for {url}: {e}")
        return None

    def _fetch_vxtwitter_safe(self, tweet_id: str) -> dict | None:
        """Fetch vxTwitter data with retry, return None on failure."""
        api_url = f"https://api.vxtwitter.com/_/status/{tweet_id}"
        for attempt in range(3):
            try:
                resp = requests.get(api_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                resp.raise_for_status()
                return resp.json()
            except (requests.exceptions.SSLError, requests.exceptions.ConnectionError):
                if attempt < 2:
                    time.sleep(1 * (attempt + 1))
            except Exception as e:
                logger.debug(f"vxTwitter attempt {attempt}: {e}")
                break
        return None

    def _build_from_jina(self, url: str, tweet_id: str,
                         jina_content: str, vx_data: dict | None) -> ParsedContent:
        """Build ParsedContent from Jina Reader content + vxTwitter metadata."""
        # Extract author and title from vxTwitter if available
        author = None
        images = []
        metadata = {"tweet_id": tweet_id}

        if vx_data:
            author_name = vx_data.get("user_name", "")
            author_handle = vx_data.get("user_screen_name", "")
            author = f"{author_name} (@{author_handle})" if author_name else author_handle
            metadata["likes"] = vx_data.get("likes")
            metadata["retweets"] = vx_data.get("retweets")

            for media_item in vx_data.get("media_extended", []):
                if media_item.get("type") == "image" and media_item.get("url"):
                    images.append(media_item["url"])

            article = vx_data.get("article")
            if article and article.get("image"):
                images.append(article["image"])

        # Build title from Jina content (first meaningful line) or vxTwitter
        title = ""
        if vx_data:
            article = vx_data.get("article")
            if article and article.get("title"):
                title = article["title"]
            else:
                text = vx_data.get("text", "")
                if text:
                    first_line = text.split("\n")[0]
                    title = first_line[:80] + ("..." if len(first_line) > 80 else "")

        if not title:
            # Extract from Jina content
            for line in jina_content.split("\n"):
                line = line.strip()
                if len(line) > 10 and not line.startswith("http"):
                    title = line[:80]
                    break
            if not title:
                title = f"X/Twitter 推文"

        # Truncate jina_content to reasonable length for AI analysis
        content = jina_content[:15000]

        # Append engagement stats
        if vx_data:
            stats = []
            for key, label in [("likes", "赞"), ("retweets", "转发"), ("replies", "回复")]:
                val = vx_data.get(key)
                if val is not None:
                    stats.append(f"{label}: {val}")
            if stats:
                content += "\n\n" + " | ".join(stats)

        return ParsedContent(
            url=url,
            platform="twitter",
            title=title,
            content=content,
            author=author,
            images=images,
            metadata=metadata,
        )

    def _build_from_vxtwitter(self, url: str, tweet_id: str, data: dict) -> ParsedContent:
        """Build ParsedContent from vxTwitter data only (no Jina)."""
        text = data.get("text", "")
        author_name = data.get("user_name", "")
        author_handle = data.get("user_screen_name", "")
        author = f"{author_name} (@{author_handle})" if author_name else author_handle

        images = []
        for media_item in data.get("media_extended", []):
            if media_item.get("type") == "image" and media_item.get("url"):
                images.append(media_item["url"])

        content_parts = [text]

        article = data.get("article")
        if article:
            if article.get("title"):
                content_parts.append(f"\n📄 文章: {article['title']}")
            if article.get("preview_text"):
                content_parts.append(article["preview_text"])

        # Follow external URLs in tweet
        linked = self._follow_embedded_urls(text)
        if linked:
            content_parts.append(f"\n--- 引用链接内容 ---\n{linked}")

        stats = []
        for key, label in [("likes", "赞"), ("retweets", "转发"), ("replies", "回复")]:
            val = data.get(key)
            if val is not None:
                stats.append(f"{label}: {val}")
        if stats:
            content_parts.append("\n" + " | ".join(stats))

        if article and article.get("title"):
            title = article["title"]
        elif text:
            first_line = text.split("\n")[0]
            title = first_line[:80] + ("..." if len(first_line) > 80 else "")
        else:
            title = f"Tweet by {author}"

        return ParsedContent(
            url=url,
            platform="twitter",
            title=title,
            content="\n".join(content_parts),
            author=author or None,
            images=images,
            metadata={"tweet_id": tweet_id, "likes": data.get("likes"), "retweets": data.get("retweets")},
        )

    def _follow_embedded_urls(self, tweet_text: str) -> str:
        """Extract and fetch external URLs embedded in tweet text."""
        urls = re.findall(r'https?://[^\s]+', tweet_text)
        results = []

        for link in urls:
            try:
                resolved = link
                if "t.co/" in link:
                    head_resp = requests.head(link, allow_redirects=True, timeout=10,
                                              headers=DEFAULT_HEADERS)
                    resolved = head_resp.url

                from urllib.parse import urlparse
                domain = urlparse(resolved).netloc.lower()
                if any(domain.endswith(skip) for skip in _SKIP_DOMAINS):
                    continue

                logger.info(f"Following embedded URL: {resolved}")
                resp = requests.get(resolved, headers=DEFAULT_HEADERS, timeout=15,
                                    allow_redirects=True)
                resp.encoding = resp.apparent_encoding or "utf-8"

                doc = Document(resp.text)
                title = doc.short_title() or ""
                soup = BeautifulSoup(doc.summary(), "lxml")
                body = soup.get_text(separator="\n", strip=True)

                if body and len(body) > 50:
                    results.append(f"**{title}**\n{body[:5000]}")

            except Exception as e:
                logger.debug(f"Failed to follow URL {link}: {e}")

        return "\n\n".join(results) if results else ""

    def _parse_oembed(self, url: str) -> ParsedContent:
        normalized = url.replace("x.com", "twitter.com")
        resp = requests.get(
            "https://publish.twitter.com/oembed",
            params={"url": normalized, "omit_script": "true"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        soup = BeautifulSoup(data.get("html", ""), "lxml")
        content = soup.get_text(separator="\n", strip=True)
        author = data.get("author_name", None)
        return ParsedContent(url=url, platform="twitter",
                             title=f"Tweet by {author}" if author else "Tweet",
                             content=content, author=author)

    def _fallback(self, url: str) -> ParsedContent:
        return ParsedContent(url=url, platform="twitter",
                             title="X/Twitter 推文",
                             content=f"[无法自动提取内容，请手动查看: {url}]")
