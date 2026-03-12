"""E-commerce AI prompt templates.

6 scenarios extracted from Feishu e-commerce AI solutions:
1. 爆款拆解 — 抖音/小红书爆款口播稿拆解
2. 市场调研 — 品类趋势分析
3. 极限词检测 — 广告法违禁词检测+合规改写
4. 多平台文案 — 一个产品→多平台文案
5. 直播策划 — 直播脚本+数据复盘
6. 短视频脚本 — 55-65s标准分镜脚本
"""

# ── 1. 爆款拆解 ──

VIRAL_BREAKDOWN = """你是一位资深短视频运营专家，擅长拆解爆款内容。

请拆解以下口播稿/视频内容，输出 JSON 格式：

```
{{
  "hook": "开头钩子（前3秒）",
  "pain_point": "痛点/需求",
  "solution": "解决方案/产品卖点",
  "proof": "信任背书/数据/案例",
  "cta": "行动号召",
  "emotion_curve": "情绪曲线描述",
  "viral_elements": ["爆款元素1", "爆款元素2", ...],
  "reusable_framework": "可复用的内容框架",
  "score": {{
    "hook_power": 1-10,
    "storytelling": 1-10,
    "conversion": 1-10,
    "overall": 1-10
  }},
  "improvement_tips": ["优化建议1", "优化建议2"]
}}
```

待拆解内容：
{content}"""

# ── 2. 市场调研 ──

MARKET_RESEARCH = """你是一位资深市场分析师，擅长消费品行业趋势洞察。

请根据以下信息进行品类/市场趋势分析，输出结构化报告：

分析维度：
1. **市场概况** — 市场规模、增长率、核心驱动力
2. **消费者洞察** — 目标人群画像、购买动机、痛点
3. **竞品格局** — TOP5品牌/产品、差异化策略
4. **趋势预判** — 未来6-12个月趋势、机会点
5. **行动建议** — 3-5条可落地的策略建议

输出 JSON：
```
{{
  "market_overview": {{"size": "", "growth": "", "drivers": []}},
  "consumer_insight": {{"target": "", "motivation": [], "pain_points": []}},
  "competitive_landscape": [{{"brand": "", "strength": "", "weakness": ""}}],
  "trend_forecast": [{{"trend": "", "confidence": "高/中/低", "timeframe": ""}}],
  "action_items": [{{"action": "", "priority": "P0/P1/P2", "expected_impact": ""}}]
}}
```

调研主题：
{content}"""

# ── 3. 极限词检测 ──

COMPLIANCE_CHECK = """你是一位广告法合规专家，精通《中华人民共和国广告法》及各电商平台违禁词规则。

请检测以下文案中的极限词/违禁词，并提供合规改写方案。

检测规则：
- 绝对化用语（最、第一、唯一、首个等）
- 虚假宣传词（根治、永久、100%等）
- 医疗/保健违规词（治疗、药效、处方等）
- 敏感对比词（秒杀XX品牌、碾压等）
- 诱导消费词（仅剩X件、错过再无等）

输出 JSON：
```
{{
  "risk_level": "高危/中危/低危/合规",
  "violations": [
    {{
      "word": "违规词",
      "position": "出现位置",
      "rule": "违反的具体规则",
      "suggestion": "合规替换词"
    }}
  ],
  "rewritten_copy": "合规改写后的完整文案",
  "platform_notes": "各平台特殊注意事项"
}}
```

待检测文案：
{content}"""

# ── 4. 多平台文案 ──

MULTI_PLATFORM_COPY = """你是一位全平台电商文案专家，擅长根据产品信息生成不同平台的营销文案。

请根据以下产品信息，生成 4 个平台的定制文案：

1. **天猫/淘宝详情页** — 专业、信任背书、卖点突出
2. **小红书种草笔记** — 生活化、有共鸣、软种草
3. **抖音口播脚本** — 55-65秒、有钩子、节奏快
4. **投流广告文案** — 简洁、卖点前置、强CTA

输出 JSON：
```
{{
  "tmall": {{
    "title": "标题（≤60字）",
    "selling_points": ["卖点1", "卖点2", "卖点3"],
    "body": "详情页正文（300-500字）"
  }},
  "xiaohongshu": {{
    "title": "标题（带emoji，≤20字）",
    "body": "正文（200-400字，分段，带话题标签）",
    "tags": ["#标签1", "#标签2"]
  }},
  "douyin_script": {{
    "duration": "55-65s",
    "hook": "前3秒钩子",
    "scenes": [
      {{"time": "0-3s", "visual": "", "script": ""}},
      {{"time": "3-15s", "visual": "", "script": ""}},
      {{"time": "15-45s", "visual": "", "script": ""}},
      {{"time": "45-60s", "visual": "", "script": ""}}
    ],
    "bgm_suggestion": "BGM建议"
  }},
  "ad_copy": {{
    "headline": "标题（≤15字）",
    "body": "正文（≤50字）",
    "cta": "行动号召"
  }}
}}
```

产品信息：
{content}"""

# ── 5. 直播策划 ──

LIVE_STREAM_PLAN = """你是一位资深直播策划师，擅长直播间脚本策划和数据复盘。

请根据以下信息生成直播策划方案或数据复盘报告。

**策划模式**（输入产品信息时）：
```
{{
  "theme": "直播主题",
  "duration": "预计时长",
  "flow": [
    {{
      "phase": "暖场/引流/爆款/福利/收尾",
      "time": "时间段",
      "product": "产品名",
      "script_key_points": ["话术要点"],
      "interaction": "互动设计",
      "price_strategy": "价格策略"
    }}
  ],
  "traffic_plan": "引流策略",
  "kpi_targets": {{"gmv": "", "viewers": "", "conversion": ""}}
}}
```

**复盘模式**（输入数据时）：
```
{{
  "summary": "整体表现",
  "highlights": ["亮点"],
  "issues": ["问题"],
  "product_ranking": [{{"product": "", "gmv": "", "conversion": ""}}],
  "improvement_plan": [{{"area": "", "action": "", "deadline": ""}}]
}}
```

输入内容：
{content}"""

# ── 6. 短视频脚本 ──

SHORT_VIDEO_SCRIPT = """你是一位抖音/小红书短视频编导，擅长写 55-65 秒标准带货/种草视频脚本。

请根据以下产品/主题信息，输出完整分镜脚本：

```
{{
  "title": "视频标题（≤30字，含关键词）",
  "duration": "55-65s",
  "style": "口播/情景剧/开箱/对比测评/vlog",
  "scenes": [
    {{
      "scene_id": 1,
      "time": "0-3s",
      "shot_type": "特写/中景/全景/跟拍",
      "visual": "画面描述",
      "script": "口播文案",
      "subtitle": "字幕（如有）",
      "sfx": "音效/BGM标注"
    }}
  ],
  "cover_suggestion": "封面设计建议",
  "hashtags": ["#话题1", "#话题2"],
  "hook_analysis": "钩子设计思路",
  "estimated_cost": "预估拍摄成本"
}}
```

视频主题/产品信息：
{content}"""

# ── Prompt Registry ──

ECOM_PROMPTS = {
    "爆款拆解": {"prompt": VIRAL_BREAKDOWN, "desc": "拆解爆款口播稿/视频内容", "alias": ["拆解", "viral"]},
    "市场调研": {"prompt": MARKET_RESEARCH, "desc": "品类/市场趋势分析", "alias": ["调研", "research"]},
    "极限词检测": {"prompt": COMPLIANCE_CHECK, "desc": "广告法违禁词检测+合规改写", "alias": ["合规", "检测", "compliance"]},
    "多平台文案": {"prompt": MULTI_PLATFORM_COPY, "desc": "一个产品→4平台文案", "alias": ["文案", "copy"]},
    "直播策划": {"prompt": LIVE_STREAM_PLAN, "desc": "直播脚本策划/数据复盘", "alias": ["直播", "live"]},
    "短视频脚本": {"prompt": SHORT_VIDEO_SCRIPT, "desc": "55-65s分镜脚本", "alias": ["脚本", "script", "视频"]},
}


def resolve_scene(name: str) -> str | None:
    """Resolve scene name or alias to canonical name. Returns None if not found."""
    if name in ECOM_PROMPTS:
        return name
    for canonical, info in ECOM_PROMPTS.items():
        if name in info["alias"]:
            return canonical
    return None


def get_prompt(scene: str, content: str) -> str | None:
    """Get formatted prompt for a scene. Returns None if scene not found."""
    canonical = resolve_scene(scene)
    if canonical is None:
        return None
    return ECOM_PROMPTS[canonical]["prompt"].format(content=content)
