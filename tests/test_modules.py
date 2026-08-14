from __future__ import annotations

import unittest

from app.modules import ModuleRegistry
from app.store import default_data


class ModuleRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = ModuleRegistry()
        self.data = default_data()

    def test_interaction_module_installs_required_sources(self):
        self.data["modules"] = {"installed": {}}
        added = self.registry.install(self.data, "services-live-bridge")
        self.assertIn("services-live-bridge", added)
        self.assertTrue(
            {"planning-center", "propresenter", "services-live-bridge"}.issubset(self.data["modules"]["installed"])
        )

    def test_page_widget_installs_owning_module(self):
        self.registry.reconcile(self.data)
        self.assertNotIn("ndi-video", self.data["modules"]["installed"])
        added = self.registry.install_for_widget_types(self.data, {"ndi"})
        self.assertEqual(added, ["ndi-video"])
        self.assertEqual(self.registry.widget_owner("ndi"), "ndi-video")

    def test_behringer_fader_widget_installs_mixer_module(self):
        self.registry.reconcile(self.data)
        self.assertNotIn("behringer-mixer", self.data["modules"]["installed"])
        self.assertEqual(self.registry.install_for_widget_types(self.data, {"behringer_faders"}), ["behringer-mixer"])
        self.assertEqual(self.registry.widget_owner("behringer_faders"), "behringer-mixer")

    def test_installed_dependency_cannot_be_removed(self):
        self.data["modules"] = {"installed": {}}
        self.registry.install(self.data, "services-live-bridge")
        with self.assertRaisesRegex(ValueError, "require ProPresenter"):
            self.registry.uninstall(self.data, "propresenter")

    def test_auto_update_advances_only_opted_in_modules(self):
        self.registry.reconcile(self.data)
        installed = self.data["modules"]["installed"]
        installed["churchboard-core"]["version"] = "1.0.0"
        installed["planning-center"]["version"] = "1.0.0"
        installed["planning-center"]["auto_update"] = False
        self.assertTrue(self.registry.reconcile(self.data))
        self.assertEqual(installed["churchboard-core"]["version"], "2.1.0")
        self.assertEqual(installed["planning-center"]["version"], "1.0.0")

    def test_frontend_catalog_declares_widget_owners(self):
        self.registry.reconcile(self.data)
        catalog = self.registry.public_frontend(self.data)["modules"]
        planning = next(item for item in catalog if item["id"] == "planning-center")
        self.assertTrue(planning["installed"])
        self.assertIn("assignments", {widget["type"] for widget in planning["widgets"]})

    def test_wireless_vendors_share_one_mics_module(self):
        catalog = self.registry.catalog(self.data)
        wireless = [item for item in catalog if item["category"] == "Wireless audio"]
        self.assertEqual([item["id"] for item in wireless], ["mics"])
        self.data["settings"]["sennheiser"]["enabled"] = True
        self.data["modules"] = {"installed": {}}
        self.registry.reconcile(self.data)
        self.assertIn("mics", self.data["modules"]["installed"])

    def test_legacy_wireless_modules_migrate_without_losing_install_state(self):
        self.data["modules"] = {"installed": {
            "shure-wireless": {"version": "2.0.0", "enabled": True, "auto_update": False},
            "sennheiser-wireless": {"version": "2.0.0", "enabled": True, "auto_update": True},
        }}
        self.assertTrue(self.registry.reconcile(self.data))
        installed = self.data["modules"]["installed"]
        self.assertNotIn("shure-wireless", installed)
        self.assertNotIn("sennheiser-wireless", installed)
        self.assertEqual(installed["mics"]["version"], "3.0.0")
        self.assertTrue(installed["mics"]["enabled"])

    def test_uninstalling_mics_disables_both_vendor_clients(self):
        self.registry.install(self.data, "mics")
        self.data["settings"]["shure"]["enabled"] = True
        self.data["settings"]["sennheiser"]["enabled"] = True
        self.registry.uninstall(self.data, "mics")
        self.assertFalse(self.data["settings"]["shure"]["enabled"])
        self.assertFalse(self.data["settings"]["sennheiser"]["enabled"])


if __name__ == "__main__":
    unittest.main()
