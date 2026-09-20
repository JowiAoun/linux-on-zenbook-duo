"""config/pipewire/10-zenduo-min-quantum.conf: the one definition of the floor.

The Nix module and ./install.sh both have to install that same file, and the
value the installer pulls out of it has to be the value the file declares. A
floor that disagrees between the two paths is a machine that wedges on one of
them and not the other, which is the worst way to find out.
"""

import os
import re
import subprocess
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
NAME = "10-zenduo-min-quantum.conf"
CONF = os.path.join(ROOT, "config", "pipewire", NAME)


def read(*parts):
    with open(os.path.join(ROOT, *parts)) as f:
        return f.read()


class ShippedConf(unittest.TestCase):
    def test_declares_the_floor_at_pipewires_own_default(self):
        m = re.search(r"^\s*default\.clock\.min-quantum\s*=\s*(\d+)", read(CONF), re.M)
        self.assertIsNotNone(m, "the floor key is gone from the shipped config")
        self.assertEqual(m.group(1), "1024",
                         "1024 is PipeWire's default quantum; a different floor needs a new measurement")

    def test_the_key_is_inside_context_properties(self):
        # PipeWire parses a key outside that block and then ignores it, which
        # looks exactly like a floor that is set.
        before, _, after = read(CONF).partition("context.properties")
        self.assertTrue(after, "no context.properties block")
        live = [ln for ln in before.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
        self.assertEqual(live, [], "a key before the block is silently ignored")
        self.assertIn("default.clock.min-quantum", after)

    def test_it_says_how_to_undo_it(self):
        text = read(CONF)
        self.assertIn("audioBufferFloor", text)
        self.assertIn("--no-audio-buffer-floor", text)


class BothInstallPaths(unittest.TestCase):
    def test_nix_module_installs_the_shipped_file(self):
        nix = read("nix", "pipewire.nix")
        self.assertIn(f'"pipewire/pipewire.conf.d/{NAME}"', nix)
        self.assertIn(f"../config/pipewire/{NAME}", nix)

    def test_home_manager_imports_the_module(self):
        self.assertIn("./pipewire.nix", read("nix", "home-manager.nix"))

    def test_installer_reads_the_same_value_the_file_declares(self):
        # Run the installer's OWN extraction against the shipped file, so this
        # fails if either the expression or the file's spelling drifts.
        m = re.search(r'floor_val="\$\((sed -nE .+?) "\$floor_src" \| head -n1\)"', read("install.sh"))
        self.assertIsNotNone(m, "install.sh no longer extracts the floor the way this test knows")
        out = subprocess.run(["bash", "-c", f'{m.group(1)} "{CONF}" | head -n1'],
                             capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "1024")

    def test_installer_and_uninstaller_name_the_same_file(self):
        self.assertIn(NAME, read("install.sh"))
        self.assertIn(NAME, read("uninstall.sh"))


if __name__ == "__main__":
    unittest.main()
