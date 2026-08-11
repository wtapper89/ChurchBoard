from __future__ import annotations

import os
import json
import tempfile
import unittest

from fastapi.testclient import TestClient

from app.main import app
from app.services.osm import parse_osm_packet


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        os.environ["CHURCHBOARD_DATA_FILE"] = os.path.join(self.directory.name, "churchboard.json")
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.directory.cleanup()
        os.environ.pop("CHURCHBOARD_DATA_FILE", None)

    def test_setup_display_and_editor_pages_load(self):
        desktop = self.client.get("/desktop")
        self.assertEqual(desktop.status_code, 200)
        self.assertIn("churchboard-logo.png", desktop.text)
        self.assertEqual(self.client.get("/", follow_redirects=False).headers["location"], "/desktop")
        admin = self.client.get("/admin", follow_redirects=False)
        self.assertEqual(admin.status_code, 307)
        self.assertEqual(admin.headers["location"], "/modules")
        setup = self.client.get("/modules")
        self.assertEqual(setup.status_code, 200)
        self.assertIn("Setup &amp; modules", setup.text)
        self.assertIn('id="core-settings-fields"', setup.text)
        module_settings = self.client.get("/static/module-settings.js").text
        self.assertIn('data-setting="timezone"', module_settings)
        self.assertIn('"obs.enabled"', module_settings)
        self.assertNotIn("pp_remote_control_enabled", module_settings)
        display = self.client.get("/display/main")
        self.assertEqual(display.status_code, 200)
        self.assertIn('class="menu-brand"', display.text)
        self.assertIn('aria-controls="display-menu"', display.text)
        self.assertIn('id="active-plan-status"', display.text)
        self.assertEqual(display.headers["cache-control"], "no-store")
        editor = self.client.get("/editor/main")
        self.assertEqual(editor.status_code, 200)
        self.assertIn("churchboard-icon.png", editor.text)
        self.assertIn('id="dashboard-background-color" type="color"', editor.text)
        self.assertIn('id="delete-dashboard"', editor.text)
        self.assertIn('input name="show_title" type="checkbox"', editor.text)
        self.assertIn('select name="slide_layout"', editor.text)
        self.assertNotIn('name="pp_remote_control_enabled"', setup.text)
        self.assertIn('ProPresenter playlist', self.client.get("/static/common.js").text)
        self.assertIn('input name="show_parts" type="checkbox"', editor.text)
        self.assertNotIn('id="dashboard-theme"', editor.text)
        self.assertNotIn('target="_blank"', editor.text)
        display_script = self.client.get("/static/display.js").text
        self.assertIn('class="board-menu-edit"', display_script)
        self.assertIn('/editor/${encodeURIComponent(item.slug)}', display_script)
        self.assertIn('planSelectionInFlight', display_script)
        self.assertIn('event.key==="Escape"', display_script)
        self.assertIn("fitDashboardToViewport", display_script)
        self.assertIn("--dashboard-scale", display_script)
        self.assertIn("resizeDashboardContent(document.querySelector(\"#dashboard\"))", display_script)
        common_script = self.client.get("/static/common.js").text
        self.assertIn('class="unassigned-board-icon"', common_script)
        self.assertIn('settings.slide_layout==="previews_only"', common_script)
        self.assertIn('settings.show_title===false', common_script)
        self.assertIn('full-service-order-list', common_script)
        self.assertIn('order_display_mode', self.client.get("/static/editor.js").text)
        self.assertIn('method:"DELETE"', self.client.get("/static/editor.js").text)
        self.assertIn('name="assignment_grouping"', self.client.get("/static/editor.js").text)
        self.assertIn('settings.card_grouping!=="position"', common_script)
        self.assertNotIn('talent-channel"><strong>', common_script)
        stylesheet = self.client.get("/static/style.css").text
        self.assertIn('mask:url("/static/churchboard-mark.svg")', stylesheet)
        mark = self.client.get("/static/churchboard-mark.svg")
        self.assertEqual(mark.status_code, 200)
        self.assertIn("<svg", mark.text)
        self.assertTrue(self.client.get("/api/app-info").json()["instance_id"])

    def test_module_manager_and_dependency_lifecycle(self):
        page = self.client.get("/modules")
        self.assertEqual(page.status_code, 200)
        self.assertIn("CHURCHBOARD 2 PRIVATE BETA", page.text)
        catalog = self.client.get("/api/modules")
        self.assertEqual(catalog.status_code, 200)
        self.assertIn("planning-center", {item["id"] for item in catalog.json()["items"]})
        installed = self.client.post("/api/modules/services-live-bridge/install")
        self.assertEqual(installed.status_code, 200)
        items = {item["id"]: item for item in installed.json()["items"]}
        self.assertTrue(items["services-live-bridge"]["installed"])
        self.assertTrue(items["planning-center"]["installed"])
        self.assertTrue(items["propresenter"]["installed"])
        blocked = self.client.delete("/api/modules/propresenter")
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("require ProPresenter", blocked.json()["detail"])
        self.assertEqual(self.client.delete("/api/modules/services-live-bridge").status_code, 204)

    def test_page_save_installs_widget_module(self):
        data = self.client.app.state.store.load()
        data.setdefault("modules", {}).setdefault("installed", {}).pop("ndi-video", None)
        self.client.app.state.store.save(data)
        board = self.client.get("/api/dashboards/main").json()
        board["widgets"].append({
            "id": "ndi-auto-module", "type": "ndi", "x": 0, "y": 20, "w": 4, "h": 3,
            "title": "NDI", "settings": {"source_name": "Stage"},
        })
        response = self.client.put("/api/dashboards/main", json=board)
        self.assertEqual(response.status_code, 200)
        catalog = {item["id"]: item for item in self.client.get("/api/modules").json()["items"]}
        self.assertTrue(catalog["ndi-video"]["installed"])

    def test_desktop_control_lists_boards_and_requires_tray_to_quit(self):
        response = self.client.get("/api/dashboards")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json()["items"]), 1)
        stopped = self.client.post("/api/desktop/quit")
        self.assertEqual(stopped.status_code, 409)

    def test_producer_bootstrap_roles_checklists_and_completion(self):
        redirect = self.client.get("/producer", follow_redirects=False)
        self.assertEqual(redirect.status_code, 303)
        owner = self.client.post("/api/auth/bootstrap", json={
            "name": "Producer Owner", "email": "owner@example.test", "password": "a strong beta password",
        })
        self.assertEqual(owner.status_code, 200)
        self.assertEqual(owner.json()["role"], "admin")
        self.assertNotIn("password_hash", owner.json())
        producer_page = self.client.get("/producer")
        self.assertEqual(producer_page.status_code, 200)
        self.assertEqual(producer_page.headers["cache-control"], "no-store")
        created = self.client.post("/api/producer/templates", json={"data": {
            "title": "Audio pre-service", "position_keys": ["production::audio"],
            "tasks": [{"title": "Turn on console", "required": True}, {"title": "Save backup", "required": False}],
        }})
        self.assertEqual(created.status_code, 201)
        template = created.json()
        context = self.client.get("/api/producer/context").json()
        self.assertEqual(context["templates"][0]["title"], "Audio pre-service")
        plans_response = self.client.get("/api/producer/plans")
        self.assertEqual(plans_response.status_code, 200)
        self.assertEqual(plans_response.headers["cache-control"], "no-store")
        self.assertEqual(plans_response.json()["items"], context["plans"])
        producer_script = self.client.get("/static/producer.js").text
        self.assertIn('producerApi("/api/producer/plans")', producer_script)
        self.assertIn("setInterval(refreshPlanChoices,5000)", producer_script)
        self.assertIn("room.startAudio()", producer_script)
        self.assertIn('addEventListener("touchstart",pressIntercom,{passive:false})', producer_script)
        self.assertIn("intercomMicrophoneError", producer_script)
        producer_css = self.client.get("/static/producer-intercom.css").text
        self.assertIn("touch-action:none", producer_css)
        self.assertIn("min-height:64px", producer_css)
        completion = self.client.put("/api/producer/completions", json={"data": {
            "service_id": "demo", "template_id": template["id"], "task_id": template["tasks"][0]["id"],
            "person_id": "person-1", "position_key": "production::audio", "completed": True,
        }})
        self.assertEqual(completion.status_code, 200)
        self.assertTrue(completion.json()["completed"])
        user = self.client.post("/api/users", json={
            "name": "Volunteer", "email": "volunteer@example.test", "password": "temporary password", "role": "volunteer",
            "campus_ids": ["main"], "planning_center_person_id": "person-1",
        })
        self.assertEqual(user.status_code, 201)

    def test_producer_account_admin_service_selection_and_passwordless_login(self):
        owner = self.client.post("/api/auth/bootstrap", json={
            "name": "Owner", "email": "owner@example.test", "password": "short",
        })
        self.assertEqual(owner.status_code, 200)
        context = self.client.get("/api/producer/context").json()
        self.assertTrue(context["plans"])
        selected = context["plans"][0]
        switched = self.client.put("/api/active-plan", json={"id": selected["id"], "service_type_id": selected["service_type_id"]})
        self.assertEqual(switched.status_code, 200)
        campus = self.client.post("/api/campuses", json={"name": "North"}).json()
        renamed = self.client.put(f"/api/campuses/{campus['id']}", json={"name": "North Campus"})
        self.assertEqual(renamed.json()["name"], "North Campus")
        passwordless = self.client.put("/api/organization/auth", json={"passwords_required": False})
        self.assertFalse(passwordless.json()["passwords_required"])
        user = self.client.post("/api/users", json={
            "name": "Jordan Lee", "email": "jordan@example.test", "role": "volunteer",
            "campus_ids": [campus["id"]], "planning_center_person_id": "1",
        }).json()
        updated = self.client.put(f"/api/users/{user['id']}", json={
            "name": "Jordan L.", "email": "jordan@example.test", "role": "editor",
            "campus_ids": [campus["id"]], "planning_center_person_id": "1",
        })
        self.assertEqual(updated.json()["role"], "editor")
        self.client.post("/api/auth/logout")
        status = self.client.get("/api/auth/status").json()
        self.assertFalse(status["passwords_required"])
        self.assertEqual({item["email"] for item in status["users"]}, {"owner@example.test", "jordan@example.test"})
        login = self.client.post("/api/auth/login", json={"email": "jordan@example.test"})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.json()["role"], "editor")
        self.client.post("/api/auth/logout")
        self.client.post("/api/auth/login", json={"email": "owner@example.test"})
        self.assertEqual(self.client.delete(f"/api/users/{user['id']}").status_code, 204)
        self.assertEqual(self.client.delete(f"/api/campuses/{campus['id']}").status_code, 204)

    def test_local_admin_recovery_reenables_password_login(self):
        self.client.post("/api/auth/bootstrap", json={"name": "Owner", "email": "owner@example.test", "password": "old"})
        self.client.put("/api/organization/auth", json={"passwords_required": False})
        self.client.post("/api/auth/logout")
        recovered = self.client.put("/api/auth/recover-admin", json={"email": "owner@example.test", "password": "new"})
        self.assertEqual(recovered.status_code, 200)
        status = self.client.get("/api/auth/status").json()
        self.assertTrue(status["passwords_required"])
        self.assertEqual(self.client.post("/api/auth/login", json={"email": "owner@example.test", "password": "new"}).status_code, 200)

    def test_demo_planning_center_people_can_be_matched_by_name(self):
        people = self.client.get("/api/integrations/planning-center/people")
        self.assertEqual(people.status_code, 200)
        self.assertEqual(people.json()["items"][0]["name"], "Jordan Lee")

    def test_dashboard_layout_export_and_import_renames_collision(self):
        exported = self.client.get("/api/layouts/main/export")
        self.assertEqual(exported.status_code, 200)
        self.assertIn("churchboard-main.json", exported.headers["content-disposition"])
        imported = self.client.post("/api/layouts/import", json=exported.json())
        self.assertEqual(imported.status_code, 200)
        self.assertEqual(imported.json()["items"][0]["slug"], "main-2")
        self.assertEqual(imported.json()["items"][0]["name"], "Main (imported)")

    def test_uploaded_position_resource_is_downloadable(self):
        resource = self.client.post("/api/producer/resources", json={"data": {
            "title": "Audio guide", "kind": "file", "position_keys": ["production::audio"],
        }}).json()
        uploaded = self.client.put(
            f"/api/producer/resources/{resource['id']}/content?filename=guide.pdf",
            content=b"sample-pdf", headers={"Content-Type": "application/pdf"},
        )
        self.assertEqual(uploaded.status_code, 200)
        downloaded = self.client.get(f"/api/producer/resources/{resource['id']}/content")
        self.assertEqual(downloaded.content, b"sample-pdf")

    def test_timezone_catalog_contains_standard_choices(self):
        response = self.client.get("/api/timezones")
        self.assertEqual(response.status_code, 200)
        zones = response.json()["items"]
        self.assertIn("UTC", zones)
        self.assertIn("America/New_York", zones)
        self.assertEqual(zones, sorted(zones))

    def test_dashboard_round_trip(self):
        board = self.client.get("/api/dashboards/main").json()
        board["name"] = "Sanctuary"
        board["background_color"] = "#213a5c"
        board["widgets"][3]["settings"]["position_keys"] = ["band::vox 2", "band::vox 1"]
        board["widgets"][3]["settings"]["position_labels"] = {"band::vox 2": {"name": "Vox 2", "team_name": "Band"}}
        response = self.client.put("/api/dashboards/main", json=board)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/dashboards/main").json()["name"], "Sanctuary")
        self.assertEqual(self.client.get("/api/dashboards/main").json()["background_color"], "#213a5c")
        saved_settings = self.client.get("/api/dashboards/main").json()["widgets"][3]["settings"]
        self.assertEqual(saved_settings["position_keys"], ["band::vox 2", "band::vox 1"])
        self.assertEqual(saved_settings["position_labels"]["band::vox 2"]["name"], "Vox 2")

    def test_deleted_playlist_widget_stays_deleted(self):
        board = self.client.get("/api/dashboards/main").json()
        board["widgets"] = [widget for widget in board["widgets"] if widget["type"] != "playlist"]
        response = self.client.put("/api/dashboards/main", json=board)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(any(widget["type"] == "playlist" for widget in response.json()["widgets"]))
        reloaded = self.client.get("/api/dashboards/main").json()
        self.assertFalse(any(widget["type"] == "playlist" for widget in reloaded["widgets"]))

    def test_default_dashboards_include_a_configured_propresenter_playlist_widget(self):
        board = self.client.get("/api/dashboards/main").json()
        playlist = next(widget for widget in board["widgets"] if widget["type"] == "playlist")
        self.assertTrue(playlist["settings"]["allow_remote_trigger"])
        self.assertEqual(playlist["settings"]["density"], "comfortable")
        self.assertTrue(playlist["settings"]["auto_scroll"])
        self.assertEqual(playlist["settings"]["active_border_color"], "#f5c400")
        editor = self.client.get("/static/editor.js").text
        self.assertIn("playlist_density", editor)
        self.assertIn("playlist_auto_scroll", editor)
        self.assertIn("playlist_active_border_color", editor)
        self.assertIn("keyboard_control_default", editor)
        self.assertNotIn("playlist_keyboard_control", editor)
        self.assertNotIn("playlist_allow_remote_trigger", editor)
        display_script = self.client.get("/static/display.js").text
        self.assertIn("data-pp-keyboard-toggle", self.client.get("/static/common.js").text)
        self.assertIn("data-pp-controls-toggle", self.client.get("/static/common.js").text)
        self.assertIn('class="pp-switch-track"', self.client.get("/static/common.js").text)
        self.assertIn('role="switch"', self.client.get("/static/common.js").text)
        self.assertIn("/api/integrations/propresenter/navigate/", display_script)
        self.assertIn("keyboardStorageKey", display_script)
        self.assertFalse(playlist["settings"]["keyboard_control_default"])

    def test_new_widgets_round_trip_and_editor_uses_a_settings_dialog(self):
        board = self.client.get("/api/dashboards/main").json()
        board["widgets"].extend([
            {"id": "pp-pad", "type": "pp_controls", "x": 0, "y": 14, "w": 4, "h": 3, "title": "ProPresenter controls", "settings": {"allow_remote_trigger": True}},
            {"id": "streams", "type": "livestreams", "x": 4, "y": 14, "w": 5, "h": 3, "title": "Livestream status", "settings": {"sources": [{"id": "youtube", "provider": "youtube", "label": "YouTube", "enabled": True}]}},
            {"id": "sermon", "type": "sermon_notes", "x": 0, "y": 17, "w": 5, "h": 5, "title": "Sermon notes", "settings": {"item_title": "Message", "field_name": "Vocals", "font_scale": 115}},
        ])
        saved = self.client.put("/api/dashboards/main", json=board)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual({widget["type"] for widget in saved.json()["widgets"][-3:]}, {"pp_controls", "livestreams", "sermon_notes"})
        editor = self.client.get("/editor/main").text
        self.assertIn('role="dialog"', editor)
        self.assertIn('id="inspector-backdrop"', editor)
        script = self.client.get("/static/editor.js").text
        self.assertIn("resize-corner", script)
        self.assertIn("openWidgetSettings", script)
        self.assertIn("livestream-source-editor", editor)
        self.assertIn("setPointerCapture", script)

    def test_livestream_api_credentials_are_kept_out_of_public_dashboards(self):
        board = self.client.get("/api/dashboards/main").json()
        board["widgets"].append({
            "id": "secure-streams", "type": "livestreams", "x": 0, "y": 15, "w": 5, "h": 3,
            "title": "Streams", "settings": {"sources": [{
                "id": "youtube", "provider": "youtube", "enabled": True,
                "channel_url": "https://www.youtube.com/@example", "api_token": "youtube-secret",
            }]},
        })
        saved = self.client.put("/api/dashboards/main", json=board)
        self.assertEqual(saved.status_code, 200)
        saved_board = saved.json()
        source = saved_board["widgets"][-1]["settings"]["sources"][0]
        self.assertNotIn("api_token", source)
        self.assertTrue(source["api_token_configured"])
        self.assertNotIn("youtube-secret", self.client.get("/api/dashboards/main").text)
        with open(os.environ["CHURCHBOARD_DATA_FILE"], encoding="utf-8") as handle:
            raw = json.load(handle)
        self.assertEqual(raw["secrets"]["livestream"]["main:secure-streams:youtube"], "youtube-secret")
        source["clear_api_token"] = True
        cleared = self.client.put("/api/dashboards/main", json=saved_board)
        self.assertFalse(cleared.json()["widgets"][-1]["settings"]["sources"][0]["api_token_configured"])
        with open(os.environ["CHURCHBOARD_DATA_FILE"], encoding="utf-8") as handle:
            self.assertNotIn("main:secure-streams:youtube", json.load(handle)["secrets"]["livestream"])

    def test_server_settings_validate_port_and_https_files(self):
        settings = self.client.get("/api/settings").json()
        settings["server"] = {"port": 70000, "https_enabled": False, "ssl_certfile": "", "ssl_keyfile": ""}
        self.assertEqual(self.client.put("/api/settings", json=settings).status_code, 400)
        settings["server"] = {"port": 8080, "https_enabled": True, "ssl_certfile": "/missing/cert.pem", "ssl_keyfile": "/missing/key.pem"}
        self.assertEqual(self.client.put("/api/settings", json=settings).status_code, 400)
        settings["server"] = {"port": 8080, "https_enabled": False, "ssl_certfile": "", "ssl_keyfile": ""}
        saved = self.client.put("/api/settings", json=settings)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["server"]["port"], 8080)

    def test_producer_media_tag_rules_are_saved(self):
        self.client.post("/api/auth/bootstrap", json={"name": "Owner", "email": "owner@example.test", "password": "beta"})
        saved = self.client.put("/api/producer/media-tag-rules", json={"items": [{
            "position_key": "production::audio", "tag_id": "tag-audio", "tag_label": "Documentation > Audio",
        }]})
        self.assertEqual(saved.status_code, 200)
        context = self.client.get("/api/producer/context").json()
        self.assertEqual(context["media_tag_rules"][0]["tag_id"], "tag-audio")
        self.assertIn("tagged_resources", context)

    def test_runtime_and_manual_service_selection(self):
        runtime = self.client.get("/api/runtime").json()
        self.assertEqual(runtime["service"]["id"], "demo")
        self.assertTrue(all(person["photo"].startswith("/static/demo-people/") for person in runtime["people"]))
        for filename in ("jordan-lee.jpg", "morgan-reed.jpg", "taylor-brooks.jpg"):
            photo = self.client.get(f"/static/demo-people/{filename}")
            self.assertEqual(photo.status_code, 200)
            self.assertEqual(photo.headers["content-type"], "image/jpeg")
        response = self.client.put("/api/active-plan", json={"id": "demo", "service_type_id": "demo"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["manual_plan"]["id"], "demo")

    def test_compact_runtime_omits_cached_planning_center_content(self):
        response = self.client.get("/api/runtime?compact=true")
        runtime = response.json()
        self.assertIn("propresenter", runtime)
        self.assertNotIn("playlist_presentations", runtime["propresenter"])
        self.assertNotIn("slides", runtime["propresenter"])
        self.assertIn("mics", runtime)
        self.assertIn("timing", runtime)
        self.assertNotIn("service_items", runtime["timing"])
        for cached_key in ("service", "people", "plans", "planning_center_media"):
            self.assertNotIn(cached_key, runtime)
        cached = self.client.get("/api/runtime?compact=true", headers={"If-None-Match": response.headers["etag"]})
        self.assertEqual(cached.status_code, 304)
        self.assertEqual(cached.content, b"")

    def test_propresenter_remote_trigger_requires_explicit_setting(self):
        response = self.client.post("/api/integrations/propresenter/active-slide", json={"index": 0})
        self.assertEqual(response.status_code, 403)
        response = self.client.post("/api/integrations/propresenter/navigate/next")
        self.assertEqual(response.status_code, 403)
        response = self.client.post("/api/integrations/propresenter/navigate/next", json={"dashboard_slug": "main", "widget_id": "playlist"})
        self.assertEqual(response.status_code, 400)

    def test_propresenter_playlist_diagnostics_requires_connection(self):
        response = self.client.get("/api/integrations/propresenter/playlist-diagnostics")
        self.assertEqual(response.status_code, 400)
        response = self.client.post("/api/integrations/propresenter/active-playlist-item", json={"index": 0})
        self.assertEqual(response.status_code, 403)

    def test_osm_measurements_are_available_as_service_reports(self):
        accepted = self.client.post("/api/integrations/osm/measurement", json={"laeq": 78.4, "peak": 92.1, "timestamp": "2026-08-05T12:00:00+00:00"})
        self.assertEqual(accepted.status_code, 202)
        services = self.client.get("/api/reports/services").json()["items"]
        self.assertEqual(services[0]["id"], "demo")
        csv_report = self.client.get("/api/reports/services/demo/spl-averages.csv")
        self.assertEqual(csv_report.status_code, 200)
        self.assertIn("Worship", csv_report.text)
        graph = self.client.get("/api/reports/services/demo/spl-graph.html")
        self.assertEqual(graph.status_code, 200)
        self.assertIn("78.4", graph.text)

    def test_osm_remote_api_levels_packet_is_normalized(self):
        packet = b'{"api":"Open Sound Meter","host":"FOH-Mac","source":"source-123","objectName":"House SPL","message":"levels","data":{"A":{"Fast":-61.6,"Slow":-63.9},"C":{"Fast":-58.2,"Slow":-59.1},"Z":{"Fast":-55.8}}}'
        parsed = parse_osm_packet(packet)
        self.assertEqual(parsed["laeq"], 78.4)
        self.assertEqual(parsed["a_slow"], 76.1)
        self.assertEqual(parsed["z_fast"], 84.2)
        self.assertEqual(parsed["c_fast"], 81.8)
        self.assertEqual(parsed["c_slow"], 80.9)
        self.assertEqual(parsed["source_id"], "source-123")
        self.assertEqual(parsed["source_name"], "House SPL")
        self.assertEqual(parsed["source_host"], "FOH-Mac")

    def test_osm_remote_api_floor_is_zero_db_spl(self):
        packet = b'{"api":"Open Sound Meter","message":"levels","data":{"A":{"Fast":-140,"Slow":-160}}}'
        parsed = parse_osm_packet(packet)
        self.assertEqual(parsed["a_fast"], 0.0)
        self.assertEqual(parsed["a_slow"], 0.0)

    def test_service_control_endpoint_takes_and_advances_service(self):
        taken = self.client.post("/api/service-control/take")
        self.assertEqual(taken.status_code, 200)
        self.assertTrue(taken.json()["service_control"]["active"])
        advanced = self.client.post("/api/service-control/next")
        self.assertEqual(advanced.status_code, 200)
        self.assertTrue(advanced.json()["service_control"]["active"])
        released = self.client.post("/api/service-control/release")
        self.assertEqual(released.status_code, 200)
        self.assertFalse(released.json()["service_control"]["active"])

    def test_planning_center_test_requires_saved_credentials(self):
        response = self.client.post("/api/integrations/planning-center/test")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Application ID", response.json()["detail"])

    def test_restream_connect_requires_saved_client_credentials(self):
        response = self.client.get("/api/integrations/restream/connect", follow_redirects=False)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Client ID", response.json()["detail"])

    def test_demo_catalog_exposes_grouped_positions(self):
        response = self.client.get("/api/integrations/planning-center/catalog")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["demo"])
        self.assertEqual(response.json()["items"][0]["name"], "Band")

    def test_named_mic_configuration_can_be_added_mapped_and_deleted(self):
        settings = self.client.get("/api/settings").json()
        settings["shure"].update({"enabled": True, "mics": [{
            "id": "blue", "name": "Blue", "host": "192.168.1.60", "port": 2202, "channel": 1,
        }]})
        settings["position_mic_map"] = {"band::vox 1": "blue"}
        saved = self.client.put("/api/settings", json=settings)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["shure"]["mics"][0]["name"], "Blue")
        self.assertEqual(saved.json()["position_mic_map"]["band::vox 1"], "blue")

        settings = saved.json()
        settings["shure"]["mics"] = []
        settings["position_mic_map"] = {}
        deleted = self.client.put("/api/settings", json=settings)
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json()["shure"]["mics"], [])

    def test_service_type_names_are_persisted_with_ids(self):
        settings = self.client.get("/api/settings").json()
        settings["planning_center"].update({"service_type_ids": ["123"], "service_types": [{"id": "123", "name": "Sunday Worship"}]})
        response = self.client.put("/api/settings", json=settings)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["planning_center"]["service_types"], [{"id": "123", "name": "Sunday Worship"}])


if __name__ == "__main__":
    unittest.main()
