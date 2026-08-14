import re


_PROGRESS_ACTIONS = (
    "继续发布",
    "继续提交",
    "提交并继续",
    "确认并继续",
    "仍要发布",
    "继续",
    "提交",
    "确认",
    "确定",
    "下一步",
    "我知道了",
    "知道了",
    "好的",
)
_AGREEMENT_ACTIONS = ("我已阅读并同意", "同意并继续", "同意")
_BLOCKING_DIALOG_WORDS = (
    "验证码",
    "短信验证",
    "人脸验证",
    "请登录",
    "登录失效",
    "额度不足",
    "每日上限",
    "字数上限",
    "审核不通过",
    "违规",
    "封禁",
    "放弃",
    "删除",
    "下架",
)
_PROGRESS_PATTERN = re.compile(r"^(?:继续|提交并继续|确认并继续|仍要发布|我已知晓|知道|好的)")


def choose_publish_progress_action(
    dialog_text: str,
    button_names: set[str],
    *,
    allow_agreement: bool = False,
) -> str | None:
    """Return one safe in-flow action, never an exit or destructive action."""
    text = dialog_text.strip()
    actions = {name.strip() for name in button_names if name.strip()}
    if any(word in text for word in _BLOCKING_DIALOG_WORDS):
        return None
    if "协议" in text or "授权" in text or "许可" in text:
        if not allow_agreement:
            return None
        for action in _AGREEMENT_ACTIONS:
            if action in actions:
                return action
    for action in _PROGRESS_ACTIONS:
        if action in actions:
            return action
    return next(
        (
            action
            for action in sorted(actions)
            if _PROGRESS_PATTERN.match(action)
        ),
        None,
    )
