"""lib/speaker_dsp.py — the one definition of the speaker chain.

The committed preset must be exactly what the generator emits, the db files
must be exactly the ones EasyEffects 8 was measured to read back, and the
easyeffectsrc merge must touch nothing but the plugins= line.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import speaker_dsp as sd  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")


class Rendering(unittest.TestCase):
    def test_committed_preset_matches_the_generator(self):
        with open(os.path.join(ROOT, "presets", "easyeffects", "duo-speakers.json")) as f:
            self.assertEqual(f.read(), sd.preset_json(), "run `make preset` after changing CHAIN")

    def test_preset_is_valid_json_with_the_chain_in_order(self):
        doc = json.loads(sd.preset_json())
        self.assertEqual(doc["output"]["plugins_order"],
                         ["filter#0", "bass_enhancer#0", "compressor#0", "limiter#0"])
        self.assertEqual(doc["output"]["filter#0"]["type"], "High-pass")
        self.assertIs(doc["output"]["limiter#0"]["gain-boost"], False)

    def test_db_files_are_exactly_what_easyeffects_8_reads(self):
        files = sd.db_files()
        self.assertEqual(files["filterrc"], "[soe][Filter#0]\nfrequency=120\nslope=2\ntype=1\n")
        self.assertEqual(files["bassEnhancerrc"],
                         "[soe][BassEnhancer#0]\namount=6\nfloor=40\nfloorActive=true\nscope=200\n")
        self.assertEqual(files["compressorrc"],
                         "[soe][Compressor#0]\nattack=10\nknee=-6\nmakeup=9\nratio=2\nrelease=150\n"
                         "releaseThreshold=-80\nthreshold=-20\n")
        self.assertEqual(files["limiterrc"],
                         "[soe][Limiter#0]\nattack=5\ngainBoost=false\nlookahead=5\nrelease=50\nthreshold=-1\n")

    def test_booleans_render_as_words_not_numbers(self):
        self.assertEqual(sd.render_value(True), "true")
        self.assertEqual(sd.render_value(False), "false")
        self.assertEqual(sd.render_value(1), "1")


class MergeRc(unittest.TestCase):
    P = "plugins=" + sd.PLUGINS_LINE

    def test_replaces_an_existing_plugins_line_only(self):
        text = "[StreamInputs]\ninputDevice=a\n\n[StreamOutputs]\noutputDevice=b\nplugins=old\n"
        self.assertEqual(sd.merge_easyeffectsrc(text),
                         f"[StreamInputs]\ninputDevice=a\n\n[StreamOutputs]\noutputDevice=b\n{self.P}\n")

    def test_adds_plugins_to_a_section_without_one(self):
        text = "[StreamOutputs]\noutputDevice=b\n"
        self.assertEqual(sd.merge_easyeffectsrc(text), f"[StreamOutputs]\noutputDevice=b\n{self.P}\n")

    def test_appends_the_section_when_missing(self):
        text = "[StreamInputs]\ninputDevice=a\n"
        self.assertEqual(sd.merge_easyeffectsrc(text), f"[StreamInputs]\ninputDevice=a\n\n[StreamOutputs]\n{self.P}\n")

    def test_plugins_line_in_another_section_is_not_ours(self):
        text = "[StreamInputs]\nplugins=inputchain\n\n[StreamOutputs]\nplugins=x\n"
        out = sd.merge_easyeffectsrc(text)
        self.assertIn("plugins=inputchain", out)
        self.assertEqual(out.count(self.P), 1)

    def test_idempotent(self):
        once = sd.merge_easyeffectsrc("[StreamOutputs]\nplugins=x\n")
        self.assertEqual(sd.merge_easyeffectsrc(once), once)


class Seeding(unittest.TestCase):
    def test_seed_install_status_uninstall_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, "easyeffects")
            self.assertTrue(sd.seed_dir(cfg))
            self.assertTrue(sd.db_seeded(cfg))
            self.assertFalse(sd.seed_dir(cfg), "second seed changes nothing")
            self.assertTrue(sd.install_preset(cfg))
            with open(os.path.join(cfg, "output", "duo-speakers.json")) as f:
                self.assertEqual(f.read(), sd.preset_json())
            # a hand-edit is overwritten again
            with open(os.path.join(cfg, "db", "filterrc"), "w") as f:
                f.write("[soe][Filter#0]\ntype=0\n")
            self.assertFalse(sd.db_seeded(cfg))
            self.assertTrue(sd.seed_dir(cfg))
            self.assertTrue(sd.db_seeded(cfg))

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, "easyeffects")
            self.assertTrue(sd.seed_dir(cfg, dry_run=True))
            self.assertFalse(os.path.exists(os.path.join(cfg, "db")))


if __name__ == "__main__":
    unittest.main()
