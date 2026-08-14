import unittest

from publisher.dialogs import choose_publish_progress_action


class PublishDialogDecisionTests(unittest.TestCase):
    def test_prefers_an_unseen_continue_submit_action_over_editing(self):
        action = choose_publish_progress_action(
            "检测提示，可继续提交或返回修改。",
            {"返回修改", "继续提交", "取消"},
        )

        self.assertEqual(action, "继续提交")

    def test_never_advances_a_login_or_quota_dialog(self):
        action = choose_publish_progress_action(
            "今日发布额度不足，请明日再试。",
            {"继续发布", "确认"},
        )

        self.assertIsNone(action)

    def test_agreement_requires_the_saved_user_consent(self):
        text = "请阅读并同意短故事发布协议后继续。"

        self.assertIsNone(
            choose_publish_progress_action(
                text,
                {"我已阅读并同意", "取消"},
            )
        )
        self.assertEqual(
            choose_publish_progress_action(
                text,
                {"我已阅读并同意", "取消"},
                allow_agreement=True,
            ),
            "我已阅读并同意",
        )

    def test_never_selects_only_a_cancel_or_destructive_action(self):
        self.assertIsNone(
            choose_publish_progress_action(
                "是否放弃当前修改？",
                {"放弃修改", "取消"},
            )
        )
