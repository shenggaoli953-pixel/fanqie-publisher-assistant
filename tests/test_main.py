from pathlib import Path
import unittest

from main import application_data_dir


class MainTests(unittest.TestCase):
    def test_build_script_propagates_pyinstaller_failures(self):
        build_script = Path(__file__).parents[1] / "build.ps1"

        self.assertIn(
            "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }",
            build_script.read_text(encoding="utf-8"),
        )

    def test_build_script_runs_the_full_regression_suite_before_packaging(self):
        build_script = Path(__file__).parents[1] / "build.ps1"

        self.assertIn(
            "python -m unittest discover -s tests -v",
            build_script.read_text(encoding="utf-8"),
        )

    def test_packaged_versions_share_the_project_data_directory(self):
        project_dir = Path(r"C:\novels\fanqie-publisher")
        executable = project_dir / "dist-update" / "FanqiePublisher" / "FanqiePublisher.exe"

        self.assertEqual(
            application_data_dir(project_dir / "main.py", executable),
            project_dir / "data",
        )
