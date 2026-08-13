from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from publisher.repository import JsonRepository
from publisher.short_story import (
    ShortStoryConfig,
    ShortStoryParseError,
    scan_short_story_source,
    suggest_short_story_categories,
    validate_short_story_config,
)


class ShortStoryTests(unittest.TestCase):
    def test_suggest_categories_keeps_only_the_central_relevant_tags(self):
        primary, extras = suggest_short_story_categories(
            "离婚九年，前夫要收回儿子的房子",
            "离婚九年后，前夫带着律师找上门，要收回留给儿子的房子。"
            "婆婆指责我自私，我决定为儿子争回这个家。",
        )

        self.assertEqual(primary, "婚姻家庭")
        self.assertEqual(extras, ("家庭", "婚恋"))
        self.assertLessEqual(len(extras), 7)

    def test_suggest_categories_does_not_promote_incidental_setting_words(self):
        primary, extras = suggest_short_story_categories(
            "离婚后，前夫送儿子去医院",
            "前夫带儿子去医院复查，医生说只是普通感冒。"
            "我在公司请了半天假，陪孩子回家休息。",
        )

        self.assertEqual(primary, "婚姻家庭")
        self.assertEqual(extras, ("婚恋", "家庭"))

    def test_suggest_categories_does_not_treat_a_family_home_as_urban_life(self):
        primary, extras = suggest_short_story_categories(
            "前夫要收回儿子的房子",
            "离婚后，前夫要收回儿子的房子。房子是儿子唯一的家，"
            "我不会把房子让给前夫。",
        )

        self.assertEqual(primary, "婚姻家庭")
        self.assertEqual(extras, ("家庭", "婚恋"))

    def test_config_rejects_a_second_primary_category_as_an_extra(self):
        with self.assertRaisesRegex(ValueError, "附加分类不能使用主分类"):
            self._build_config(
                story_id="meteor",
                name="流星",
                source_path=Path("流星.txt"),
                cover_path=Path("cover.jpg"),
                primary_category="婚姻家庭",
                extra_categories=("虐心婚恋",),
            )

    def test_config_load_discards_an_old_primary_category_extra(self):
        config = ShortStoryConfig.from_dict(
            {
                "story_id": "meteor",
                "name": "流星",
                "source_path": "流星.txt",
                "cover_path": "cover.jpg",
                "primary_category": "婚姻家庭",
                "extra_categories": ["虐心婚恋"],
            }
        )

        self.assertEqual(config.extra_categories, ())

    def test_suggest_categories_leaves_neutral_story_unclassified(self):
        primary, extras = suggest_short_story_categories(
            "午后随笔",
            "窗外的风吹过树叶，桌上的茶慢慢凉了。",
        )

        self.assertEqual(primary, "")
        self.assertEqual(extras, ())

    def test_scan_txt_file_uses_file_stem_as_title(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "流星.txt"
            path.write_text("第一段\n第二段", encoding="utf-8")

            draft = self._scan(path)

        self.assertEqual(draft.title, "流星")
        self.assertEqual(draft.body, "第一段\n第二段")
        self.assertEqual(draft.source_files, (path,))

    def test_scan_markdown_strips_matching_first_heading_only_from_upload_copy(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "夜航.md"
            source = "# 夜航\n\n起飞。\n平稳。"
            path.write_text(source, encoding="utf-8")

            draft = self._scan(path)
            saved_source = path.read_text(encoding="utf-8")

        self.assertEqual(draft.title, "夜航")
        self.assertEqual(draft.body, "起飞。\n平稳。")
        self.assertEqual(saved_source, source)

    def test_scan_directory_merges_supported_files_in_natural_order(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "群星"
            root.mkdir()
            (root / "2-尾声.txt").write_text("尾声", encoding="utf-8")
            (root / "10-补遗.md").write_text("补遗", encoding="utf-8")
            (root / "1-开场.md").write_text("# 群星\n\n开场", encoding="utf-8")
            (root / "notes.docx").write_text("ignored", encoding="utf-8")

            draft = self._scan(root)

        self.assertEqual(draft.title, "群星")
        self.assertEqual(
            [file.name for file in draft.source_files],
            ["1-开场.md", "2-尾声.txt", "10-补遗.md"],
        )
        self.assertEqual(draft.body, "开场\n\n尾声\n\n补遗")

    def test_scan_supports_gb18030_encoded_sources(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "桂花.txt"
            path.write_bytes("桂花开了".encode("gb18030"))

            draft = self._scan(path)

        self.assertEqual(draft.body, "桂花开了")

    def test_scan_rejects_empty_body_after_heading_cleanup(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "空白.md"
            path.write_text("# 空白\n\n", encoding="utf-8")

            with self.assertRaises(ShortStoryParseError):
                self._scan(path)

    def test_config_allows_missing_paths_until_publish_time(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self._build_config(
                story_id="meteor",
                name="流星",
                source_path=root / "missing.txt",
                cover_path=root / "missing.jpg",
                primary_category="科幻",
            )

        self.assertEqual(config.story_id, "meteor")

    def test_config_allows_eight_categories_in_total(self):
        config = self._build_config(
            story_id="meteor",
            name="流星",
            source_path=Path("流星.txt"),
            cover_path=Path("cover.jpg"),
            primary_category="婚姻家庭",
            extra_categories=(
                "追妻火葬场",
                "打脸逆袭",
                "家庭",
                "现代",
                "豪门世家",
                "白月光",
                "爽文",
            ),
        )

        self.assertEqual(len((config.primary_category, *config.extra_categories)), 8)

    def test_config_rejects_more_than_eight_categories(self):
        with self.assertRaisesRegex(ValueError, "最多选择 8 个分类"):
            self._build_config(
                story_id="meteor",
                name="流星",
                source_path=Path("流星.txt"),
                cover_path=Path("cover.jpg"),
            primary_category="婚姻家庭",
            extra_categories=(
                "追妻火葬场",
                "打脸逆袭",
                "家庭",
                "现代",
                "豪门世家",
                "白月光",
                "爽文",
                "甜宠",
                ),
            )

    def test_validate_short_story_config_reports_missing_source(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cover = root / "cover.jpg"
            cover.write_bytes(b"jpg")
            config = self._build_config(
                story_id="meteor",
                name="流星",
                source_path=root / "missing.txt",
                cover_path=cover,
                primary_category="科幻",
            )

            with self.assertRaisesRegex(ValueError, "正文源文件不存在"):
                validate_short_story_config(config)

    def test_validate_short_story_config_reports_missing_cover(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "流星.txt"
            source.write_text("正文", encoding="utf-8")
            config = self._build_config(
                story_id="meteor",
                name="流星",
                source_path=source,
                cover_path=root / "missing.jpg",
                primary_category="科幻",
            )

            with self.assertRaisesRegex(ValueError, "封面文件不存在"):
                validate_short_story_config(config)

    def test_repository_round_trip_uses_defaults_for_old_short_story_data(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "夜航.md"
            cover = root / "cover.jpg"
            source.write_text("正文", encoding="utf-8")
            cover.write_bytes(b"jpg")
            repository = JsonRepository(root / "data")
            (root / "data" / "short_stories.json").write_text(
                """
[
  {
    "story_id": "night-flight",
    "name": "夜航",
    "source_path": "%s",
    "cover_path": "%s",
    "primary_category": "都市"
  }
]
                """
                % (str(source).replace("\\", "\\\\"), str(cover).replace("\\", "\\\\")),
                encoding="utf-8",
            )

            stories = repository.load_short_stories()

        self.assertEqual(len(stories), 1)
        self.assertEqual(stories[0].extra_categories, ())
        self.assertTrue(stories[0].ai_generated)
        self.assertTrue(stories[0].trial_enabled)
        self.assertFalse(stories[0].consent_confirmed)
        self.assertIsNone(stories[0].remote_draft_url)

    def test_repository_loads_short_story_when_saved_paths_are_missing(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = JsonRepository(root / "data")
            (root / "data" / "short_stories.json").write_text(
                """
[
  {
    "story_id": "night-flight",
    "name": "夜航",
    "source_path": "%s",
    "cover_path": "%s",
    "primary_category": "都市"
  }
]
                """
                % (
                    str(root / "lost.md").replace("\\", "\\\\"),
                    str(root / "lost.jpg").replace("\\", "\\\\"),
                ),
                encoding="utf-8",
            )

            stories = repository.load_short_stories()

        self.assertEqual(len(stories), 1)
        self.assertEqual(stories[0].source_path.name, "lost.md")
        self.assertEqual(stories[0].cover_path.name, "lost.jpg")

    def test_repository_saves_short_stories_atomically(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "霜降.txt"
            cover = root / "cover.png"
            source.write_text("正文", encoding="utf-8")
            cover.write_bytes(b"png")
            repository = JsonRepository(root / "data")

            repository.save_short_stories(
                [
                    self._build_config(
                        story_id="frost",
                        name="霜降",
                        source_path=source,
                        cover_path=cover,
                        primary_category="悬疑",
                        extra_categories=("现实情感",),
                        ai_generated=False,
                        trial_enabled=False,
                        consent_confirmed=True,
                        remote_draft_url=(
                            "https://fanqienovel.com/main/writer/publish-short/123"
                        ),
                    )
                ]
            )

            saved = repository.load_short_stories()

        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].story_id, "frost")
        self.assertFalse(saved[0].ai_generated)
        self.assertEqual(
            saved[0].remote_draft_url,
            "https://fanqienovel.com/main/writer/publish-short/123",
        )
        self.assertFalse((root / "data" / "short_stories.json.tmp").exists())

    def _scan(self, path: Path):
        return scan_short_story_source(path)

    def _build_config(self, **overrides):
        return ShortStoryConfig(**overrides)
