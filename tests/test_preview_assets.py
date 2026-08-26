import importlib.util
import shutil
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "generate_preview_assets", ROOT / "scripts" / "generate_preview_assets.py"
)
assert SPEC and SPEC.loader
PREVIEW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREVIEW)


@unittest.skipUnless(shutil.which("magick"), "ImageMagick is required")
class PreviewAssetTests(unittest.TestCase):
    def test_committed_final_assets_are_safe_and_well_formed(self) -> None:
        pngs = (
            ROOT / "preview.png",
            ROOT / "assets" / "screenshots" / "panel.png",
            ROOT / "assets" / "screenshots" / "panel-reduced-motion.png",
        )
        gif = ROOT / "assets" / "demo.gif"

        for path in (*pngs, gif):
            PREVIEW.verify_dimensions(path)
            PREVIEW.verify_final_asset(path)
        self.assertLessEqual(PREVIEW.verify_gif_timing(gif), PREVIEW.MAX_GIF_DURATION_CS)

    def test_final_text_rejects_non_demo_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-demo ID"):
            PREVIEW.scan_final_text('taskId="real-task-123"', Path("preview.png"), "test")

    def test_live_readme_capture_is_safe_and_cropped(self) -> None:
        live = ROOT / "assets" / "screenshots" / "live-panel.png"
        PREVIEW.verify_final_asset(live)
        dimensions = PREVIEW.run(["magick", "identify", "-format", "%Wx%H", str(live)])
        self.assertEqual(dimensions, "844x1305")

    def test_marketplace_preview_matches_generated_panel(self) -> None:
        self.assertEqual(
            (ROOT / "preview.png").read_bytes(),
            (ROOT / "assets" / "screenshots" / "panel.png").read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
