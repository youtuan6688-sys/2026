"""Bitable Template System — 预设多场景表结构，一键建表。

每个模板定义：
- fields: 字段列表（名称、类型、选项等）
- views: 建议视图配置
- ai_rules: AI 自动处理规则（可选）
- description: 场景说明

字段类型映射（飞书 API）：
  1=多行文本, 2=数字, 3=单选, 4=多选, 5=日期,
  7=复选框, 11=人员, 13=电话, 15=超链接, 17=附件,
  18=单向关联, 20=公式, 21=双向关联, 1001=创建时间,
  1002=最后更新时间, 1003=创建人, 1004=修改人
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FieldDef:
    """Single field definition for a Bitable table."""
    name: str
    type: int  # 飞书字段类型编号
    options: dict[str, Any] = field(default_factory=dict)
    # options 用于单选/多选的预设值、数字格式、日期格式等


@dataclass(frozen=True)
class AIRule:
    """AI auto-processing rule for a template."""
    source_field: str
    target_field: str
    prompt: str
    model: str = ""  # 空 = 默认模型


@dataclass(frozen=True)
class BitableTemplate:
    """Complete template for creating a Bitable table."""
    name: str
    description: str
    category: str  # video, content, project, crm, ecom, custom
    fields: tuple[FieldDef, ...]
    ai_rules: tuple[AIRule, ...] = ()
    tags: tuple[str, ...] = ()


# ============================================================
# 场景模板定义
# ============================================================

VIDEO_BREAKDOWN = BitableTemplate(
    name="视频拆解分析",
    description="爆款视频逐秒拆解 + 整体诊断，适用于抖音/小红书/YouTube",
    category="video",
    tags=("视频", "拆解", "抖音", "小红书", "内容分析"),
    fields=(
        FieldDef("视频标题", 1),
        FieldDef("作者", 1),
        FieldDef("平台", 3, {"options": [
            {"name": "抖音"}, {"name": "小红书"}, {"name": "YouTube"},
            {"name": "B站"}, {"name": "视频号"},
        ]}),
        FieldDef("视频链接", 15),
        FieldDef("点赞数", 2, {"formatter": "0"}),
        FieldDef("评论数", 2, {"formatter": "0"}),
        FieldDef("收藏数", 2, {"formatter": "0"}),
        FieldDef("转发数", 2, {"formatter": "0"}),
        FieldDef("发布日期", 5, {"date_formatter": "yyyy-MM-dd"}),
        FieldDef("视频时长", 1),
        FieldDef("品牌/产品", 1),
        FieldDef("Hook类型", 3, {"options": [
            {"name": "痛点开场"}, {"name": "悬念开场"}, {"name": "数据开场"},
            {"name": "对比开场"}, {"name": "故事开场"}, {"name": "热点开场"},
            {"name": "反常识开场"}, {"name": "情绪开场"},
        ]}),
        FieldDef("叙事结构", 4, {"options": [
            {"name": "PAS"}, {"name": "AIDA"}, {"name": "故事型"},
            {"name": "教程型"}, {"name": "对比型"}, {"name": "列表型"},
            {"name": "问答型"}, {"name": "挑战型"},
        ]}),
        FieldDef("目标人群", 1),
        FieldDef("核心USP", 1),
        FieldDef("说服机制", 4, {"options": [
            {"name": "痛点共鸣"}, {"name": "权威背书"}, {"name": "社交认同"},
            {"name": "稀缺性"}, {"name": "利益驱动"}, {"name": "情感触发"},
            {"name": "场景代入"}, {"name": "数据说服"},
        ]}),
        FieldDef("综合评分", 2, {"formatter": "0"}),
        FieldDef("可复用性评分", 2, {"formatter": "0"}),
        FieldDef("套用建议", 1),
        FieldDef("AI分析摘要", 1),
    ),
    ai_rules=(
        AIRule(
            source_field="AI分析摘要",
            target_field="套用建议",
            prompt="基于以下视频分析，提炼3-5条可复用的内容策略建议，每条50字以内：\n{content}",
        ),
    ),
)

VIDEO_SCRIPT_TIMELINE = BitableTemplate(
    name="逐秒脚本拆解",
    description="视频逐秒/逐段脚本拆解，关联到视频拆解主表",
    category="video",
    tags=("视频", "脚本", "逐秒拆解"),
    fields=(
        FieldDef("时间段", 1),
        FieldDef("画面描述", 1),
        FieldDef("台词/文案", 1),
        FieldDef("镜头类型", 3, {"options": [
            {"name": "特写"}, {"name": "中景"}, {"name": "全景"},
            {"name": "转场"}, {"name": "字幕卡"}, {"name": "产品展示"},
        ]}),
        FieldDef("功能标签", 4, {"options": [
            {"name": "Hook"}, {"name": "痛点"}, {"name": "解决方案"},
            {"name": "产品展示"}, {"name": "使用教程"}, {"name": "效果对比"},
            {"name": "情感共鸣"}, {"name": "CTA"}, {"name": "转场"},
        ]}),
        FieldDef("情绪曲线", 3, {"options": [
            {"name": "⬆️ 上升"}, {"name": "➡️ 平稳"}, {"name": "⬇️ 下降"},
            {"name": "⚡ 高潮"}, {"name": "🔄 转折"},
        ]}),
        FieldDef("BGM/音效", 1),
        FieldDef("备注", 1),
    ),
)

CONTENT_CALENDAR = BitableTemplate(
    name="内容日历",
    description="多平台内容发布计划 + 排期 + 状态跟踪",
    category="content",
    tags=("内容", "日历", "排期", "多平台"),
    fields=(
        FieldDef("内容标题", 1),
        FieldDef("平台", 4, {"options": [
            {"name": "抖音"}, {"name": "小红书"}, {"name": "B站"},
            {"name": "视频号"}, {"name": "知乎"}, {"name": "公众号"},
            {"name": "YouTube"}, {"name": "X/Twitter"},
        ]}),
        FieldDef("内容类型", 3, {"options": [
            {"name": "短视频"}, {"name": "图文"}, {"name": "长视频"},
            {"name": "直播"}, {"name": "文章"}, {"name": "轮播图"},
        ]}),
        FieldDef("状态", 3, {"options": [
            {"name": "💡 选题"}, {"name": "📝 撰写中"}, {"name": "🎬 制作中"},
            {"name": "👀 待审核"}, {"name": "📅 已排期"}, {"name": "✅ 已发布"},
            {"name": "❌ 已弃用"},
        ]}),
        FieldDef("计划发布日期", 5, {"date_formatter": "yyyy-MM-dd"}),
        FieldDef("实际发布日期", 5, {"date_formatter": "yyyy-MM-dd"}),
        FieldDef("负责人", 1),
        FieldDef("选题来源", 3, {"options": [
            {"name": "热点追踪"}, {"name": "竞品分析"}, {"name": "用户反馈"},
            {"name": "原创策划"}, {"name": "系列内容"}, {"name": "AI推荐"},
        ]}),
        FieldDef("关键词/标签", 4),
        FieldDef("脚本/文案", 1),
        FieldDef("素材链接", 15),
        FieldDef("发布链接", 15),
        FieldDef("数据-浏览", 2, {"formatter": "0"}),
        FieldDef("数据-点赞", 2, {"formatter": "0"}),
        FieldDef("数据-评论", 2, {"formatter": "0"}),
        FieldDef("数据-转发", 2, {"formatter": "0"}),
        FieldDef("复盘笔记", 1),
    ),
)

PROJECT_TRACKER = BitableTemplate(
    name="项目跟踪",
    description="通用项目/任务管理，适用于开发、运营、活动等",
    category="project",
    tags=("项目", "任务", "管理", "看板"),
    fields=(
        FieldDef("任务名称", 1),
        FieldDef("状态", 3, {"options": [
            {"name": "📋 待办"}, {"name": "🔄 进行中"}, {"name": "👀 待验收"},
            {"name": "✅ 已完成"}, {"name": "🚫 已取消"},
        ]}),
        FieldDef("优先级", 3, {"options": [
            {"name": "🔴 紧急"}, {"name": "🟡 重要"}, {"name": "🟢 普通"}, {"name": "⚪ 低"},
        ]}),
        FieldDef("负责人", 1),
        FieldDef("开始日期", 5, {"date_formatter": "yyyy-MM-dd"}),
        FieldDef("截止日期", 5, {"date_formatter": "yyyy-MM-dd"}),
        FieldDef("进度%", 2, {"formatter": "0%"}),
        FieldDef("分类", 3, {"options": [
            {"name": "开发"}, {"name": "运营"}, {"name": "设计"},
            {"name": "测试"}, {"name": "文档"}, {"name": "其他"},
        ]}),
        FieldDef("描述", 1),
        FieldDef("备注", 1),
        FieldDef("相关链接", 15),
    ),
)

CRM_CONTACTS = BitableTemplate(
    name="客户管理CRM",
    description="客户/合作方信息管理 + 跟进记录 + 阶段追踪",
    category="crm",
    tags=("CRM", "客户", "销售", "跟进"),
    fields=(
        FieldDef("公司名称", 1),
        FieldDef("联系人", 1),
        FieldDef("职位", 1),
        FieldDef("手机", 13),
        FieldDef("邮箱", 1),
        FieldDef("微信", 1),
        FieldDef("客户阶段", 3, {"options": [
            {"name": "🔍 线索"}, {"name": "📞 初步接触"}, {"name": "💬 需求沟通"},
            {"name": "📄 方案提案"}, {"name": "🤝 签约合作"}, {"name": "🔄 持续服务"},
            {"name": "❄️ 暂停/流失"},
        ]}),
        FieldDef("客户来源", 3, {"options": [
            {"name": "主动找来"}, {"name": "转介绍"}, {"name": "展会"},
            {"name": "线上投放"}, {"name": "行业活动"}, {"name": "老客户"},
        ]}),
        FieldDef("行业", 1),
        FieldDef("预算范围", 3, {"options": [
            {"name": "10万以下"}, {"name": "10-50万"}, {"name": "50-100万"},
            {"name": "100万以上"}, {"name": "待确认"},
        ]}),
        FieldDef("最近跟进日期", 5, {"date_formatter": "yyyy-MM-dd"}),
        FieldDef("跟进记录", 1),
        FieldDef("合作内容", 1),
        FieldDef("备注", 1),
    ),
)

ECOM_PRODUCT = BitableTemplate(
    name="电商商品管理",
    description="商品信息 + 价格 + 库存 + 多平台状态",
    category="ecom",
    tags=("电商", "商品", "SKU", "库存"),
    fields=(
        FieldDef("商品名称", 1),
        FieldDef("SKU", 1),
        FieldDef("品类", 3, {"options": [
            {"name": "护肤"}, {"name": "彩妆"}, {"name": "个护"},
            {"name": "母婴"}, {"name": "食品"}, {"name": "保健"},
            {"name": "家居"}, {"name": "其他"},
        ]}),
        FieldDef("品牌", 1),
        FieldDef("售价", 2, {"formatter": "0.00"}),
        FieldDef("成本价", 2, {"formatter": "0.00"}),
        FieldDef("库存量", 2, {"formatter": "0"}),
        FieldDef("上架平台", 4, {"options": [
            {"name": "淘宝"}, {"name": "天猫"}, {"name": "京东"},
            {"name": "拼多多"}, {"name": "抖音"}, {"name": "小红书"},
        ]}),
        FieldDef("状态", 3, {"options": [
            {"name": "在售"}, {"name": "预热"}, {"name": "下架"}, {"name": "清仓"},
        ]}),
        FieldDef("主图链接", 15),
        FieldDef("商品链接", 15),
        FieldDef("月销量", 2, {"formatter": "0"}),
        FieldDef("利润率", 2, {"formatter": "0%"}),
        FieldDef("备注", 1),
    ),
)

COMPETITOR_ANALYSIS = BitableTemplate(
    name="竞品分析",
    description="竞品账号/产品对比分析，适用于品牌调研",
    category="content",
    tags=("竞品", "分析", "调研", "品牌"),
    fields=(
        FieldDef("竞品名称", 1),
        FieldDef("平台", 3, {"options": [
            {"name": "抖音"}, {"name": "小红书"}, {"name": "天猫"},
            {"name": "京东"}, {"name": "拼多多"},
        ]}),
        FieldDef("账号/店铺", 1),
        FieldDef("粉丝量", 2, {"formatter": "0"}),
        FieldDef("月发布频次", 2, {"formatter": "0"}),
        FieldDef("平均互动量", 2, {"formatter": "0"}),
        FieldDef("内容风格", 1),
        FieldDef("爆款策略", 1),
        FieldDef("定价区间", 1),
        FieldDef("优势", 1),
        FieldDef("劣势", 1),
        FieldDef("可借鉴点", 1),
        FieldDef("更新日期", 5, {"date_formatter": "yyyy-MM-dd"}),
        FieldDef("分析师", 1),
    ),
)

KNOWLEDGE_BASE = BitableTemplate(
    name="知识库索引",
    description="文章/资料/学习资源统一管理，适合团队知识沉淀",
    category="content",
    tags=("知识库", "文章", "学习", "资源"),
    fields=(
        FieldDef("标题", 1),
        FieldDef("来源", 3, {"options": [
            {"name": "公众号"}, {"name": "知乎"}, {"name": "X/Twitter"},
            {"name": "GitHub"}, {"name": "YouTube"}, {"name": "书籍"},
            {"name": "播客"}, {"name": "其他"},
        ]}),
        FieldDef("分类", 4, {"options": [
            {"name": "AI工具"}, {"name": "技术"}, {"name": "营销"},
            {"name": "产品"}, {"name": "设计"}, {"name": "商业"},
            {"name": "行业"}, {"name": "方法论"},
        ]}),
        FieldDef("链接", 15),
        FieldDef("摘要", 1),
        FieldDef("关键词", 4),
        FieldDef("可吸收度", 3, {"options": [
            {"name": "⭐⭐⭐⭐⭐ 极高"}, {"name": "⭐⭐⭐⭐ 高"},
            {"name": "⭐⭐⭐ 中"}, {"name": "⭐⭐ 低"}, {"name": "⭐ 存档"},
        ]}),
        FieldDef("状态", 3, {"options": [
            {"name": "待阅读"}, {"name": "已阅读"}, {"name": "已吸收"},
            {"name": "已落地"},
        ]}),
        FieldDef("入库日期", 5, {"date_formatter": "yyyy-MM-dd"}),
        FieldDef("笔记", 1),
    ),
)

PROMPT_LIBRARY = BitableTemplate(
    name="Prompt素材库",
    description="AI提示词管理，按六维结构存储，适用于出图/视频/文案",
    category="content",
    tags=("prompt", "AI", "出图", "模板"),
    fields=(
        FieldDef("Prompt名称", 1),
        FieldDef("用途", 3, {"options": [
            {"name": "图片生成"}, {"name": "视频生成"}, {"name": "文案生成"},
            {"name": "代码生成"}, {"name": "数据分析"}, {"name": "翻译"},
        ]}),
        FieldDef("模型", 3, {"options": [
            {"name": "Gemini"}, {"name": "Claude"}, {"name": "GPT"},
            {"name": "Midjourney"}, {"name": "Seedance"}, {"name": "Flux"},
            {"name": "通用"},
        ]}),
        FieldDef("Prompt正文", 1),
        FieldDef("风格标签", 4, {"options": [
            {"name": "写实"}, {"name": "动漫"}, {"name": "赛博朋克"},
            {"name": "宫崎骏"}, {"name": "新海诚"}, {"name": "鸟山明"},
            {"name": "水墨"}, {"name": "极简"}, {"name": "复古"},
        ]}),
        FieldDef("质量评分", 2, {"formatter": "0"}),
        FieldDef("使用次数", 2, {"formatter": "0"}),
        FieldDef("示例输出链接", 15),
        FieldDef("备注", 1),
    ),
)

LIVE_STREAM_PLAN = BitableTemplate(
    name="直播策划",
    description="直播排期 + 商品清单 + 话术脚本 + 数据复盘",
    category="ecom",
    tags=("直播", "带货", "电商", "策划"),
    fields=(
        FieldDef("直播主题", 1),
        FieldDef("直播日期", 5, {"date_formatter": "yyyy-MM-dd HH:mm"}),
        FieldDef("平台", 3, {"options": [
            {"name": "抖音"}, {"name": "小红书"}, {"name": "视频号"},
            {"name": "淘宝"}, {"name": "快手"},
        ]}),
        FieldDef("主播", 1),
        FieldDef("状态", 3, {"options": [
            {"name": "策划中"}, {"name": "准备中"}, {"name": "直播中"},
            {"name": "已结束"}, {"name": "已复盘"},
        ]}),
        FieldDef("商品清单", 1),
        FieldDef("话术脚本", 1),
        FieldDef("目标GMV", 2, {"formatter": "0"}),
        FieldDef("实际GMV", 2, {"formatter": "0"}),
        FieldDef("观看人数", 2, {"formatter": "0"}),
        FieldDef("最高在线", 2, {"formatter": "0"}),
        FieldDef("转化率", 2, {"formatter": "0%"}),
        FieldDef("复盘笔记", 1),
    ),
)


# ============================================================
# 模板注册表
# ============================================================

TEMPLATE_REGISTRY: dict[str, BitableTemplate] = {
    "video": VIDEO_BREAKDOWN,
    "video_script": VIDEO_SCRIPT_TIMELINE,
    "content": CONTENT_CALENDAR,
    "project": PROJECT_TRACKER,
    "crm": CRM_CONTACTS,
    "ecom": ECOM_PRODUCT,
    "competitor": COMPETITOR_ANALYSIS,
    "knowledge": KNOWLEDGE_BASE,
    "prompt": PROMPT_LIBRARY,
    "live": LIVE_STREAM_PLAN,
}

# 中文别名映射
TEMPLATE_ALIASES: dict[str, str] = {
    "视频拆解": "video",
    "视频脚本": "video_script",
    "逐秒拆解": "video_script",
    "内容日历": "content",
    "内容排期": "content",
    "项目管理": "project",
    "任务管理": "project",
    "客户管理": "crm",
    "电商": "ecom",
    "商品管理": "ecom",
    "竞品分析": "competitor",
    "知识库": "knowledge",
    "prompt": "prompt",
    "提示词": "prompt",
    "直播": "live",
    "直播策划": "live",
}


def get_template(name: str) -> BitableTemplate | None:
    """Get template by key or Chinese alias."""
    key = TEMPLATE_ALIASES.get(name, name)
    return TEMPLATE_REGISTRY.get(key)


def list_templates() -> list[dict[str, str]]:
    """List all available templates."""
    return [
        {
            "key": key,
            "name": tpl.name,
            "description": tpl.description,
            "category": tpl.category,
            "field_count": str(len(tpl.fields)),
        }
        for key, tpl in TEMPLATE_REGISTRY.items()
    ]


def list_templates_formatted() -> str:
    """Format template list for chat display."""
    lines = ["📋 **可用模板列表**\n"]
    by_category: dict[str, list] = {}
    for key, tpl in TEMPLATE_REGISTRY.items():
        by_category.setdefault(tpl.category, []).append((key, tpl))

    category_names = {
        "video": "🎬 视频",
        "content": "📝 内容",
        "project": "📊 项目",
        "crm": "🤝 客户",
        "ecom": "🛒 电商",
        "custom": "🔧 自定义",
    }

    for cat, items in by_category.items():
        lines.append(f"\n**{category_names.get(cat, cat)}**")
        for key, tpl in items:
            lines.append(f"  `{key}` — {tpl.name}（{len(tpl.fields)}字段）")

    lines.append(f"\n用法: `/bt create <模板名>` 一键建表")
    return "\n".join(lines)
