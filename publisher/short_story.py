from dataclasses import dataclass
from pathlib import Path
import re


SHORT_STORY_CATEGORIES = (
    "婚姻家庭",
    "女生生活",
    "男生生活",
    "现言甜宠",
    "虐心婚恋",
    "青春虐恋",
    "男生情感",
    "女性成长",
    "悬疑惊悚",
    "玄幻仙侠",
    "宫斗宅斗",
    "男频衍生",
    "女频衍生",
    "年代",
    "纯爱",
    "其他",
    "古言甜宠",
    "古风世情",
    "都市日常",
    "男频脑洞",
    "女频脑洞",
    "民国旧影",
    "古言虐恋",
    "历史古代",
    "追妻火葬场",
    "追夫火葬场",
    "真假千金",
    "先婚后爱",
    "打脸逆袭",
    "破镜重圆",
    "系统",
    "金手指",
    "大女主",
    "女性互助",
    "穿越",
    "重生",
    "暗恋",
    "婚恋",
    "权谋",
    "架空",
    "养崽文",
    "团宠",
    "无限流",
    "末日求生",
    "游戏动漫",
    "规则怪谈",
    "民间奇闻",
    "影视",
    "科幻",
    "推理",
    "直播",
    "升级流",
    "外卖",
    "鉴宝",
    "黑道",
    "都市江湖",
    "都市异能",
    "仕途",
    "白月光",
    "霸总",
    "婆媳",
    "青梅竹马",
    "姐弟恋",
    "凤凰男",
    "校花校草",
    "女配",
    "医生",
    "替身",
    "病娇",
    "赘婿",
    "校霸",
    "影帝影后",
    "萌宝",
    "糙汉",
    "万人迷",
    "女总裁",
    "奶爸",
    "神医",
    "特种兵",
    "首富",
    "魔法",
    "吸血鬼",
    "欧美帮派",
    "狼人",
    "先虐后甜",
    "甜宠",
    "虐文",
    "爽文",
    "救赎",
    "惊悚",
    "励志",
    "沙雕搞笑",
    "家庭",
    "职场",
    "校园",
    "娱乐圈",
    "现代",
    "古代",
    "豪门世家",
    "西幻魔法",
    "西方古典",
    "西方现代",
)

SHORT_STORY_PRIMARY_CATEGORIES = SHORT_STORY_CATEGORIES[:24]
SHORT_STORY_EXTRA_CATEGORIES = SHORT_STORY_CATEGORIES[24:]

_CATEGORY_KEYWORDS = {
    "婚姻家庭": ("离婚", "结婚", "前夫", "前妻", "丈夫", "妻子", "老公", "老婆", "婆婆", "岳母", "儿子", "女儿", "婚礼", "彩礼"),
    "女生生活": ("闺蜜", "美妆", "租房", "女同事", "合租", "瑜伽", "口红"),
    "男生生活": ("兄弟", "哥们", "球赛", "工地", "修车", "钓鱼", "酒局"),
    "现言甜宠": ("甜宠", "闪婚", "总裁", "豪门", "宠妻", "撒娇", "告白", "恋爱"),
    "虐心婚恋": ("离婚", "前夫", "前妻", "背叛", "出轨", "家暴", "流产", "白月光", "虐恋"),
    "青春虐恋": ("高中", "大学", "校园", "同桌", "校花", "校草", "毕业", "青春"),
    "男生情感": ("初恋", "女友", "失恋", "求婚", "前女友", "恋人"),
    "女性成长": ("独立", "创业", "职场", "逆袭", "成长", "女强人", "重启人生"),
    "悬疑惊悚": ("凶手", "尸体", "杀人", "谋杀", "失踪", "推理", "案件", "恐怖", "鬼", "刑警"),
    "玄幻仙侠": ("修仙", "仙尊", "灵根", "宗门", "渡劫", "法宝", "魔尊", "炼丹"),
    "宫斗宅斗": ("皇后", "嫔妃", "后宫", "王妃", "嫡女", "庶女", "宅斗", "侯府"),
    "男频衍生": ("奥特曼", "火影", "海贼", "斗罗", "漫威", "赛博"),
    "女频衍生": ("综影视", "甄嬛", "如懿", "知否", "宝可梦", "哈利波特"),
    "年代": ("七零", "八零", "九零", "年代", "知青", "下乡", "粮票", "大院"),
    "纯爱": ("双男主", "耽美", "男朋友", "同性", "学长", "竹马"),
    "古言甜宠": ("王爷", "王妃", "王府", "赐婚", "夫君", "娘子", "宠妃"),
    "古风世情": ("古代", "江湖", "镖局", "茶楼", "掌柜", "书院", "县令"),
    "都市日常": ("都市", "上班", "公司", "小区", "外卖", "地铁", "出租车"),
    "男频脑洞": ("系统", "末世", "神豪", "直播", "特种兵", "高武", "觉醒"),
    "女频脑洞": ("穿书", "重生", "真假千金", "团宠", "读心", "空间", "攻略"),
    "民国旧影": ("民国", "军阀", "少帅", "旗袍", "上海滩", "姨太太"),
    "古言虐恋": ("和离", "冷宫", "废后", "赐死", "灭门", "守寡", "虐恋"),
    "历史古代": ("大唐", "三国", "明朝", "清朝", "皇帝", "将军", "边关", "战场"),
}

_EXTRA_CATEGORY_KEYWORDS = {
    "婚恋": ("离婚", "结婚", "前夫", "前妻", "丈夫", "妻子", "婚姻"),
    "家庭": ("房子", "儿子", "女儿", "父母", "婆婆", "岳母", "家庭"),
    "虐文": ("离婚", "前夫", "前妻", "背叛", "出轨", "家暴", "流产", "虐恋"),
    "婆媳": ("婆婆", "婆媳", "儿媳"),
    "打脸逆袭": ("打脸", "逆袭", "翻身", "报复", "反击", "争回", "夺回"),
    "现代": ("现代", "都市", "当下", "律师", "医院", "小区", "手机", "微信"),
    "追妻火葬场": ("追妻", "挽回", "后悔", "求复合", "回头"),
    "追夫火葬场": ("追夫", "追回", "求原谅"),
    "先婚后爱": ("先婚后爱", "闪婚", "契约婚姻"),
    "破镜重圆": ("破镜重圆", "复合", "重逢"),
    "真假千金": ("真假千金", "真千金", "假千金", "认亲"),
    "系统": ("系统", "任务面板", "绑定系统"),
    "金手指": ("金手指", "空间", "灵泉", "外挂"),
    "大女主": ("大女主", "女强", "女王", "独当一面"),
    "女性互助": ("女性互助", "姐妹", "闺蜜", "帮她"),
    "穿越": ("穿越", "穿书", "穿回", "异世"),
    "重生": ("重生", "重新来过", "上一世", "前世"),
    "暗恋": ("暗恋", "偷偷喜欢", "暗自喜欢"),
    "权谋": ("权谋", "朝堂", "夺嫡", "谋反"),
    "架空": ("架空", "虚构王朝", "异国"),
    "养崽文": ("养崽", "带娃", "育儿", "奶粉"),
    "团宠": ("团宠", "全家宠", "团团"),
    "无限流": ("无限流", "副本", "玩家", "通关"),
    "末日求生": ("末日", "丧尸", "求生", "避难所"),
    "游戏动漫": ("游戏", "动漫", "二次元", "电竞"),
    "规则怪谈": ("规则怪谈", "规则", "怪谈", "禁忌"),
    "民间奇闻": ("民间", "奇闻", "风水", "阴阳"),
    "影视": ("影视", "剧组", "综艺", "剧本"),
    "科幻": ("科幻", "星际", "机器人", "人工智能"),
    "推理": ("推理", "凶手", "案件", "侦探"),
    "直播": ("直播", "主播", "弹幕"),
    "升级流": ("升级", "境界", "经验值", "打怪"),
    "外卖": ("外卖", "骑手", "送餐"),
    "鉴宝": ("鉴宝", "古董", "玉石", "捡漏"),
    "黑道": ("黑道", "帮派", "混混"),
    "都市江湖": ("江湖", "地痞", "社会大哥"),
    "都市异能": ("异能", "超能力", "觉醒"),
    "仕途": ("仕途", "官场", "书记", "市长"),
    "白月光": ("白月光", "朱砂痣"),
    "霸总": ("霸总", "总裁", "总裁夫人"),
    "青梅竹马": ("青梅竹马", "青梅", "竹马"),
    "姐弟恋": ("姐弟恋", "年下", "姐姐"),
    "凤凰男": ("凤凰男", "扶弟魔"),
    "校花校草": ("校花", "校草"),
    "女配": ("女配", "恶毒女配", "炮灰"),
    "医生": ("医生", "医院", "主治医"),
    "替身": ("替身", "替代品", "长得像"),
    "病娇": ("病娇", "偏执", "占有欲"),
    "赘婿": ("赘婿", "上门女婿"),
    "校霸": ("校霸", "校痞"),
    "影帝影后": ("影帝", "影后", "演员"),
    "萌宝": ("萌宝", "宝宝", "小宝贝"),
    "糙汉": ("糙汉", "硬汉"),
    "万人迷": ("万人迷", "众人喜欢"),
    "女总裁": ("女总裁", "女老板"),
    "奶爸": ("奶爸", "单亲爸爸"),
    "神医": ("神医", "医术", "针灸"),
    "特种兵": ("特种兵", "部队", "军区"),
    "首富": ("首富", "富豪", "千亿"),
    "魔法": ("魔法", "法师", "魔杖"),
    "吸血鬼": ("吸血鬼", "血族"),
    "欧美帮派": ("欧美", "黑手党", "教父"),
    "狼人": ("狼人", "狼族"),
    "先虐后甜": ("先虐后甜", "误会解除", "苦尽甘来"),
    "甜宠": ("甜宠", "宠妻", "宠夫", "撒娇"),
    "爽文": ("爽文", "爽感", "扬眉吐气", "大快人心"),
    "救赎": ("救赎", "治愈", "救下"),
    "惊悚": ("恐怖", "惊悚", "鬼", "尸体"),
    "励志": ("励志", "奋斗", "坚持", "梦想"),
    "沙雕搞笑": ("沙雕", "搞笑", "爆笑", "喜剧"),
    "职场": ("职场", "上司", "同事", "公司"),
    "校园": ("校园", "高中", "大学", "同桌"),
    "娱乐圈": ("娱乐圈", "艺人", "经纪人"),
    "古代": ("古代", "江湖", "镖局", "茶楼", "掌柜", "书院", "县令", "王爷", "王妃"),
    "豪门世家": ("豪门", "家族", "继承人"),
    "西幻魔法": ("西幻", "魔法", "精灵", "骑士"),
    "西方古典": ("中世纪", "庄园", "贵族"),
    "西方现代": ("纽约", "伦敦", "美国", "欧洲"),
}


class ShortStoryParseError(ValueError):
    pass


@dataclass(frozen=True)
class ShortStoryConfig:
    story_id: str
    name: str
    source_path: Path
    cover_path: Path
    primary_category: str
    extra_categories: tuple[str, ...] = ()
    ai_generated: bool = True
    trial_enabled: bool = True
    consent_confirmed: bool = False
    remote_draft_url: str | None = None

    def __post_init__(self) -> None:
        if not self.story_id.strip():
            raise ValueError("story_id must not be empty")
        if not self.name.strip():
            raise ValueError("name must not be empty")
        if not self.primary_category.strip():
            raise ValueError("primary_category must not be empty")
        if len((self.primary_category, *self.extra_categories)) > 8:
            raise ValueError("番茄短故事最多选择 8 个分类")
        if any(
            category in SHORT_STORY_PRIMARY_CATEGORIES
            for category in self.extra_categories
        ):
            raise ValueError("附加分类不能使用主分类")

    def to_dict(self) -> dict[str, object]:
        return {
            "story_id": self.story_id,
            "name": self.name,
            "source_path": str(self.source_path),
            "cover_path": str(self.cover_path),
            "primary_category": self.primary_category,
            "extra_categories": list(self.extra_categories),
            "ai_generated": self.ai_generated,
            "trial_enabled": self.trial_enabled,
            "consent_confirmed": self.consent_confirmed,
            "remote_draft_url": self.remote_draft_url,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "ShortStoryConfig":
        raw_extra_categories = value.get("extra_categories", [])
        if not isinstance(raw_extra_categories, list):
            raise ValueError("extra_categories must be a list")
        primary_category = str(value["primary_category"])
        extra_categories = tuple(
            str(item)
            for item in raw_extra_categories
            if str(item) not in SHORT_STORY_PRIMARY_CATEGORIES
        )
        return cls(
            story_id=str(value["story_id"]),
            name=str(value["name"]),
            source_path=Path(str(value["source_path"])),
            cover_path=Path(str(value["cover_path"])),
            primary_category=primary_category,
            extra_categories=extra_categories,
            ai_generated=bool(value.get("ai_generated", True)),
            trial_enabled=bool(value.get("trial_enabled", True)),
            consent_confirmed=bool(value.get("consent_confirmed", False)),
            remote_draft_url=(
                str(value["remote_draft_url"])
                if value.get("remote_draft_url")
                else None
            ),
        )


@dataclass(frozen=True)
class ShortStoryDraft:
    title: str
    body: str
    source_path: Path
    source_files: tuple[Path, ...]
    character_count: int


def suggest_short_story_categories(title: str, body: str) -> tuple[str, tuple[str, ...]]:
    title = title.strip()
    body = body[:20000]
    ranked = sorted(
        (
            (category, _category_score(title, body, keywords))
            for category, keywords in _CATEGORY_KEYWORDS.items()
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    primary, primary_score = ranked[0]
    if primary_score < 4:
        return "", ()
    extras = tuple(
        category
        for category, score in sorted(
            (
                (category, _category_score(title, body, keywords))
                for category, keywords in _EXTRA_CATEGORY_KEYWORDS.items()
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        if score > 0
    )[:7]
    return primary, extras


def _category_score(title: str, body: str, keywords: tuple[str, ...]) -> int:
    return sum(
        title.count(keyword) * 4 + min(body.count(keyword), 3)
        for keyword in keywords
    )


def validate_short_story_config(config: ShortStoryConfig) -> None:
    if not config.source_path.exists():
        raise ValueError(f"正文源文件不存在: {config.source_path}")
    if not config.cover_path.exists():
        raise ValueError(f"封面文件不存在: {config.cover_path}")


def scan_short_story_source(path: Path) -> ShortStoryDraft:
    if path.is_file():
        source_files = (path,)
        default_title = path.stem
    elif path.is_dir():
        source_files = tuple(_scan_supported_files(path))
        default_title = path.name
    else:
        raise ShortStoryParseError(f"短故事来源不存在: {path}")

    if not source_files:
        raise ShortStoryParseError("未找到可发布的 .txt 或 .md 正文")

    raw_sections = [_read_text(file_path) for file_path in source_files]
    heading = _extract_first_heading(raw_sections[0], default_title)
    title = heading or default_title
    cleaned_sections = [_cleanup_first_section(raw_sections[0], title), *raw_sections[1:]]
    body = "\n\n".join(
        section.strip() for section in cleaned_sections if section.strip()
    ).strip()
    if not body:
        raise ShortStoryParseError("短故事正文不能为空")

    return ShortStoryDraft(
        title=title,
        body=body,
        source_path=path,
        source_files=source_files,
        character_count=len(re.sub(r"\s+", "", body)),
    )


def _scan_supported_files(root: Path) -> list[Path]:
    supported = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".txt", ".md"}
    ]
    return sorted(supported, key=lambda path: _natural_path_key(path.relative_to(root)))


def _natural_path_key(path: Path) -> tuple[tuple[object, ...], ...]:
    return tuple(_natural_name_key(part) for part in path.parts)


def _natural_name_key(value: str) -> tuple[object, ...]:
    parts = re.split(r"(\d+)", value)
    key: list[object] = []
    for part in parts:
        if not part:
            continue
        key.append(int(part) if part.isdigit() else part.lower())
    return tuple(key)


def _cleanup_first_section(text: str, title: str) -> str:
    lines = text.splitlines()
    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index >= len(lines):
        return ""

    heading = _normalize_heading_line(lines[index], title)
    if heading is None or heading != _normalize_title(title):
        return text

    index += 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    return "\n".join(lines[index:])


def _extract_first_heading(text: str, default_title: str) -> str | None:
    for line in text.splitlines():
        normalized = _normalize_heading_line(line, default_title)
        if normalized is None:
            if line.strip():
                return None
            continue
        return normalized
    return None


def _normalize_heading_line(line: str, default_title: str) -> str | None:
    stripped = line.strip()
    if not stripped:
        return None
    if stripped.startswith("#"):
        stripped = stripped.lstrip("#").strip()
        return _normalize_title(stripped) if stripped else None

    normalized = _normalize_title(stripped)
    if normalized == _normalize_title(default_title):
        return normalized
    return None


def _normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _read_text(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ShortStoryParseError(f"无法读取短故事编码: {path}")
