"""
Gemini 出图 Prompt 模板库
基于六要素框架 + SCHEMA 方法论
优先手机 APP 零成本出图

六要素：背景设定 → 主体描述 → 环境细节 → 技术参数 → 风格指导 → 情感氛围
关键：叙述性描述 > 关键词堆叠（效果提升 85%）
"""

# ── 风格基底 ──────────────────────────────────────────

STYLE_BASES = {
    "ue5_cinematic": (
        "虚幻引擎5实时渲染品质，CG电影级画面，"
        "全局光照，体积光，景深效果，8K超高清，PBR材质，光线追踪反射，"
        "电影感、高级感、质感"
    ),
    "photo_realistic": (
        "专业摄影级画面，自然光线，真实材质纹理，"
        "浅景深虚化背景，高动态范围，细腻色彩过渡，"
        "如同高端相机实拍"
    ),
    "anime_ghibli": (
        "宫崎骏吉卜力工作室风格，手绘水彩质感，"
        "柔和的光影过渡，温暖的色调，细腻的自然描绘，"
        "充满治愈感和生命力的画面"
    ),
    "anime_shinkai": (
        "新海诚风格，极致的光影表现，云层细节丰富，"
        "通透的蓝天，逆光效果，精细的城市背景，"
        "画面如同梦境般美丽"
    ),
    "ink_wash": (
        "中国水墨写意画风格，留白构图，宣纸质感，"
        "流畅笔法，墨色浓淡层次分明，极简意境"
    ),
    "cyberpunk": (
        "赛博朋克风格，霓虹灯光，雨夜反射，"
        "紫色青色主色调，黑暗氛围，未来科技感，电影级构图"
    ),
    "flat_design": (
        "扁平设计风格，几何色块，简洁线条，"
        "明亮配色，无阴影或极简阴影，现代感UI风格"
    ),
    "dragonball": (
        "鸟山明龙珠风格，硬朗线条，动态姿势，"
        "能量光效，漫画网点，夸张的透视和速度线"
    ),
}

# ── 相机控制术语 ─────────────────────────────────────

CAMERA_PRESETS = {
    "portrait": "85mm portrait lens, f/2.8, 浅景深人像虚化",
    "wide": "wide-angle shot, 广角全景开阔感",
    "macro": "macro shot, 微距纹理细节特写",
    "low_angle": "low-angle perspective, 仰视角度，威严感",
    "bird_eye": "bird's eye view, 俯视全局",
    "dutch": "Dutch angle, 倾斜戏剧感",
    "cinematic": "anamorphic lens, 2.39:1 电影画幅, cinematic composition",
    "product_45": "45度俯拍，三点式柔光照明，产品居中",
}

# ── 文字排版指令 ─────────────────────────────────────

TEXT_LAYOUTS = {
    "xiaohongshu": (
        "图片上方用醒目的中文艺术字体写标题（大号、有设计感），"
        "图片下方小字写话题标签，所有文字必须是中文"
    ),
    "douyin_cover": (
        "画面中央偏上位置放大标题文字（粗体白色描边），"
        "底部半透明黑色条带内放副标题，竖版 9:16"
    ),
    "clean_no_text": "画面内不放任何文字，保持纯净构图",
    "logo_centered": (
        "品牌 Logo 居中，文字清晰锐利（bold Sans-Serif），"
        "高对比度背景，商务简约"
    ),
    "poster": (
        "电影海报排版，主视觉占 70%，标题在上 1/4 区域，"
        "演职员表小字在底部，字体有设计感"
    ),
}

# ── 宽高比 ───────────────────────────────────────────

ASPECT_RATIOS = {
    "xiaohongshu": "3:4（竖版，适合小红书）",
    "douyin": "9:16（竖版，适合抖音/TikTok）",
    "widescreen": "16:9（横版，适合B站/YouTube封面）",
    "square": "1:1（正方形，适合朋友圈/Instagram）",
    "cinema": "2.39:1（超宽银幕电影画幅）",
}


# ── Prompt 构建器 ────────────────────────────────────

def build_prompt(
    subject: str,
    *,
    style: str = "photo_realistic",
    camera: str = "cinematic",
    aspect: str = "xiaohongshu",
    mood: str = "",
    background: str = "",
    prohibitions: str = "",
    text_layout: str = "clean_no_text",
    title: str = "",
    hashtags: list[str] | None = None,
) -> str:
    """通用 Prompt 构建器 — 基于六要素框架

    Args:
        subject: 主体描述（最重要的部分）
        style: 风格基底 key（见 STYLE_BASES）
        camera: 相机预设 key（见 CAMERA_PRESETS）
        aspect: 宽高比 key（见 ASPECT_RATIOS）
        mood: 情感氛围，如 "温暖治愈" "紧张刺激"
        background: 背景/环境细节
        prohibitions: 不要出现的元素（语义负提示）
        text_layout: 文字排版 key（见 TEXT_LAYOUTS）
        title: 标题文字（如果需要）
        hashtags: 话题标签列表
    """
    parts = ["Generate an image:\n"]

    # 1. 主体
    parts.append(f"主体：{subject}")

    # 2. 背景/环境
    if background:
        parts.append(f"环境：{background}")

    # 3. 技术参数
    cam = CAMERA_PRESETS.get(camera, camera)
    ratio = ASPECT_RATIOS.get(aspect, aspect)
    parts.append(f"镜头：{cam}")
    parts.append(f"画面比例：{ratio}")

    # 4. 风格
    style_desc = STYLE_BASES.get(style, style)
    parts.append(f"风格：{style_desc}")

    # 5. 情感
    if mood:
        parts.append(f"氛围：{mood}")

    # 6. 负提示（语义化）
    if prohibitions:
        parts.append(f"画面要求：{prohibitions}")

    # 文字
    layout = TEXT_LAYOUTS.get(text_layout, text_layout)
    if text_layout != "clean_no_text":
        parts.append(f"文字排版：{layout}")
        if title:
            parts.append(f'标题文字："{title}"')
        if hashtags:
            tags_str = " ".join(f"#{t}" for t in hashtags)
            parts.append(f'底部标签："{tags_str}"')

    return "\n".join(parts)


# ── 向后兼容：旧版小红书封面构建器 ────────────────────

def build_cover_prompt(
    title: str,
    scene: str,
    hashtags: list[str],
    mood: str = "暖色调、舒适、治愈",
) -> str:
    """构建小红书封面图的 Gemini prompt（向后兼容）"""
    return build_prompt(
        subject=scene,
        style="ue5_cinematic",
        camera="cinematic",
        aspect="xiaohongshu",
        mood=mood,
        text_layout="xiaohongshu",
        title=title,
        hashtags=hashtags,
    )


# ── 预设场景模板（扩展版）────────────────────────────

SCENE_TEMPLATES = {
    # --- 小红书/探店 ---
    "咖啡探店": {
        "subject": "一杯精致的拿铁咖啡，拉花完美，放在深色大理石桌面上",
        "background": "有格调的精品咖啡馆，窗外透进柔和的午后光线，散落的咖啡豆点缀",
        "style": "photo_realistic",
        "camera": "product_45",
        "mood": "暖色调、慵懒、下午茶氛围",
        "hashtags": ["探店日记", "咖啡控必看"],
    },
    "美食探店": {
        "subject": "一道精致的料理特写，食材新鲜有光泽",
        "background": "高档餐厅的柔和灯光",
        "style": "photo_realistic",
        "camera": "macro",
        "mood": "暖色调、食欲感、高级感",
        "hashtags": ["美食探店", "吃货日记"],
    },
    "穿搭分享": {
        "subject": "一套时尚穿搭的静物摆拍，衣物质感分明，搭配饰品和鲜花",
        "background": "大理石/木质桌面，自然光",
        "style": "photo_realistic",
        "camera": "product_45",
        "mood": "干净、高级、杂志感",
        "hashtags": ["穿搭灵感", "日常穿搭"],
    },
    "旅行打卡": {
        "subject": "一个绝美的旅行景点，前景有人的背影",
        "background": "黄金时刻光线，云层层次分明",
        "style": "photo_realistic",
        "camera": "wide",
        "mood": "震撼、治愈、电影感",
        "hashtags": ["旅行日记", "打卡攻略"],
    },
    "居家好物": {
        "subject": "一件精致的家居好物特写，搭配绿植和柔和灯光",
        "background": "简洁的桌面，北欧风背景",
        "style": "photo_realistic",
        "camera": "product_45",
        "mood": "温馨、治愈、生活感",
        "hashtags": ["家居好物", "提升幸福感"],
    },

    # --- 营销/商务 ---
    "产品摄影": {
        "subject": "产品置于纯白背景，突出材质纹理",
        "background": "纯白无缝背景纸，三点式柔光照明",
        "style": "photo_realistic",
        "camera": "product_45",
        "mood": "专业、简洁、商业级",
        "prohibitions": "画面干净无杂物，无多余装饰，无文字水印",
        "hashtags": ["产品摄影", "电商素材"],
    },
    "品牌海报": {
        "subject": "品牌主视觉大图，视觉冲击力强",
        "style": "ue5_cinematic",
        "camera": "cinematic",
        "aspect": "widescreen",
        "text_layout": "poster",
        "mood": "高端、大气、品牌感",
        "hashtags": ["品牌设计", "视觉营销"],
    },

    # --- 动漫/创意 ---
    "吉卜力风景": {
        "subject": "一片广阔的绿色草原，远处有小木屋，天空中飘着棉花糖般的白云",
        "background": "远山层叠，小溪蜿蜒流过",
        "style": "anime_ghibli",
        "camera": "wide",
        "mood": "治愈、宁静、充满生命力",
        "hashtags": ["吉卜力", "治愈系"],
    },
    "新海诚天空": {
        "subject": "少年站在天台上仰望天空，校服随风飘动",
        "background": "极致的蓝天白云，逆光效果，城市天际线",
        "style": "anime_shinkai",
        "camera": "low_angle",
        "mood": "青春、怀念、如梦如幻",
        "hashtags": ["新海诚", "动漫风景"],
    },
    "龙珠战斗": {
        "subject": "肌肉发达的战士蓄力发出能量波，头发金色竖起",
        "background": "荒野大地碎裂，能量光柱冲天",
        "style": "dragonball",
        "camera": "low_angle",
        "mood": "热血、震撼、力量爆发",
        "hashtags": ["龙珠", "动漫"],
    },
    "赛博朋克街景": {
        "subject": "一个穿着机械改装的人行走在雨夜街头",
        "background": "两侧高楼林立的霓虹灯招牌，地面积水倒映灯光",
        "style": "cyberpunk",
        "camera": "dutch",
        "mood": "孤独、科幻、未来废土",
        "hashtags": ["赛博朋克", "未来世界"],
    },

    # --- 中国风 ---
    "水墨山水": {
        "subject": "远山近水，一叶扁舟，渔翁独钓",
        "background": "山间云雾缭绕，松柏点缀",
        "style": "ink_wash",
        "camera": "wide",
        "mood": "空灵、禅意、悠远",
        "hashtags": ["水墨画", "中国风"],
    },
    "古风人物": {
        "subject": "身着汉服的女子手持团扇，回眸浅笑",
        "background": "桃花树下，花瓣飘落，月门回廊",
        "style": "ink_wash",
        "camera": "portrait",
        "mood": "古典、温婉、诗意",
        "hashtags": ["古风", "汉服"],
    },

    # --- AI/科技内容 ---
    "AI工具教程封面": {
        "subject": "一个发光的AI机器人正在操作全息屏幕，屏幕上显示代码和图表",
        "background": "深色科技感办公室，蓝紫色主色调",
        "style": "ue5_cinematic",
        "camera": "cinematic",
        "mood": "科技感、未来、专业",
        "text_layout": "douyin_cover",
        "hashtags": ["AI工具", "效率提升"],
    },
    "数据可视化": {
        "subject": "3D立体的数据图表从平面升起，柱状图和折线图发出柔和蓝光",
        "background": "深色磨砂玻璃质感桌面，周围有小型全息投影",
        "style": "ue5_cinematic",
        "camera": "low_angle",
        "mood": "专业、高端、科技感",
        "hashtags": ["数据分析", "可视化"],
    },
}


def build_from_template(template_name: str, title: str = "") -> str:
    """从预设模板构建 prompt"""
    tpl = SCENE_TEMPLATES[template_name]
    return build_prompt(
        subject=tpl["subject"],
        style=tpl.get("style", "photo_realistic"),
        camera=tpl.get("camera", "cinematic"),
        aspect=tpl.get("aspect", "xiaohongshu"),
        mood=tpl.get("mood", ""),
        background=tpl.get("background", ""),
        prohibitions=tpl.get("prohibitions", ""),
        text_layout=tpl.get("text_layout", "clean_no_text"),
        title=title,
        hashtags=tpl.get("hashtags"),
    )
