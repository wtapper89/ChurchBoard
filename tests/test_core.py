from __future__ import annotations

import asyncio
import base64
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.models import Dashboard
from app.services.planning_center import PlanningCenterClient, calculate_timing, consolidate_people, item_leader, people_for_service_time, position_key, selected_service_time, service_items
from app.services.livekit import HostedIntercomServer, access_token
from app.services.ndi import NDIRuntime
from app.services.media_cache import PlanningCenterMediaCache
from app.services.shure import ShureClient, battery_percent, percent, transmitter_active
from app.services.sennheiser import parse_ssc_response, ssc_request
from app.services.propresenter import ProPresenterClient
from app.services.restream import RestreamClient
from app.services.runtime import RuntimeService
from app.store import ConfigStore


class StoreTests(unittest.TestCase):
    def test_store_migrates_producer_platform_collections(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "churchboard.json")
            data = store.load()
            self.assertEqual(data["version"], 3)
            self.assertFalse(data["organization"]["auth_enabled"])
            self.assertTrue(data["organization"]["passwords_required"])
            self.assertEqual(data["organization"]["campuses"][0]["id"], "main")
            self.assertEqual(data["producer"]["checklist_templates"], [])

    def test_new_store_contains_destination_dashboards(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "state.json")
            self.assertEqual([item["slug"] for item in store.load()["dashboards"]], ["main", "green-room", "audio"])
            self.assertEqual(store.load()["dashboards"][0]["widgets"][3]["type"], "assignments")
            self.assertEqual(store.load()["dashboards"][2]["widgets"][3]["settings"]["display_mode"], "technical")
            self.assertEqual(store.load()["dashboards"][0]["widgets"][3]["settings"]["card_grouping"], "person")
            self.assertFalse(store.load()["dashboards"][0]["widgets"][3]["settings"]["use_planning_center_icon"])
            self.assertEqual(store.load()["dashboards"][0]["widgets"][3]["settings"]["unassigned_media_title"], "Icon")
            self.assertEqual(store.load()["dashboards"][0]["widgets"][5]["settings"]["display_mode"], "current")
            self.assertEqual(store.load()["dashboards"][0]["background_color"], "#0a0d12")
            slides = store.load()["dashboards"][0]["widgets"][4]["settings"]
            self.assertEqual(slides["slide_layout"], "full")
            self.assertTrue(slides["show_parts"])
            self.assertNotIn("theme", store.load()["dashboards"][0])
            self.assertEqual(store.load()["settings"]["planning_center"]["service_types"], [])
            self.assertEqual(store.load()["settings"]["server"]["producer_port"], 80)
            self.assertTrue(store.load()["settings"]["server"]["producer_port_enabled"])
            self.assertEqual(store.load()["settings"]["intercom"]["party_lines"][0]["id"], "production")
            self.assertFalse(store.load()["settings"]["ndi"]["enabled"])

    def test_light_theme_migrates_to_dark_customizable_background(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "state.json")
            data = store.load()
            data["dashboards"][0].pop("background_color", None)
            data["dashboards"][0]["theme"] = "light"
            store.save(data)
            board = store.load()["dashboards"][0]
            self.assertEqual(board["background_color"], "#0a0d12")
            self.assertNotIn("theme", board)

    def test_old_mic_widget_migrates_to_combined_assignments(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "state.json")
            data = store.load()
            data["dashboards"][0]["widgets"][3].update({"type": "mics", "title": "Microphones"})
            store.save(data)
            widget = store.load()["dashboards"][0]["widgets"][3]
            self.assertEqual(widget["type"], "assignments")
            self.assertEqual(widget["title"], "Scheduled Positions & Mics")

    def test_order_widget_migrates_to_current_display_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "state.json")
            data = store.load()
            data["dashboards"][0]["widgets"][5]["settings"].pop("display_mode")
            store.save(data)
            self.assertEqual(store.load()["dashboards"][0]["widgets"][5]["settings"]["display_mode"], "current")

    def test_assignment_widget_migrates_to_person_card_grouping(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "state.json")
            data = store.load()
            data["dashboards"][0]["widgets"][3]["settings"].pop("card_grouping")
            store.save(data)
            self.assertEqual(store.load()["dashboards"][0]["widgets"][3]["settings"]["card_grouping"], "person")

    def test_public_settings_never_returns_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "state.json")
            data = store.load()
            data["settings"]["planning_center"]["secret"] = "do-not-return"
            data["settings"]["restream"]["access_token"] = "also-do-not-return"
            data["settings"]["intercom"]["api_secret"] = "livekit-secret"
            store.save(data)
            public = store.public_settings()["planning_center"]
            self.assertEqual(public["secret"], "")
            self.assertTrue(public["secret_configured"])
            restream = store.public_settings()["restream"]
            self.assertEqual(restream["access_token"], "")
            self.assertTrue(restream["access_token_configured"])
            intercom = store.public_settings()["intercom"]
            self.assertEqual(intercom["api_secret"], "")
            self.assertTrue(intercom["api_secret_configured"])
            self.assertEqual(intercom["api_key"], "")
            self.assertEqual(intercom["url"], "")

    def test_ndi_sdk_root_resolves_the_nested_macos_runtime(self):
        with patch("app.services.ndi.platform.system", return_value="Darwin"):
            candidates = [str(path) for path in NDIRuntime._candidates("/Library/NDI SDK for Apple")]
        self.assertIn("/Library/NDI SDK for Apple/lib/macOS/libndi.dylib", candidates)

    def test_livekit_token_has_audio_room_grant_and_role_metadata(self):
        token = access_token(
            "api-key", "api-secret", "churchboard-user-1", "Jordan Lee",
            "churchboard-production", {"role": "admin", "party_line_id": "production"},
        )
        encoded_payload = token.split(".")[1]
        encoded_payload += "=" * (-len(encoded_payload) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded_payload))
        self.assertEqual(payload["iss"], "api-key")
        self.assertEqual(payload["sub"], "churchboard-user-1")
        self.assertEqual(payload["video"]["room"], "churchboard-production")
        self.assertTrue(payload["video"]["canPublish"])
        self.assertEqual(payload["video"]["canPublishSources"], ["microphone"])
        self.assertEqual(json.loads(payload["metadata"])["role"], "admin")

    def test_hosted_intercom_config_uses_fixed_local_ports_and_private_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            service = HostedIntercomServer(Path(directory) / "churchboard.json")
            config = service._write_config("churchboard-key", "12345678901234567890123456789012")
            contents = config.read_text(encoding="utf-8")
            self.assertIn("port: 7880", contents)
            self.assertIn("tcp_port: 7881", contents)
            self.assertIn("udp_port: 7882", contents)
            self.assertIn('"churchboard-key": "12345678901234567890123456789012"', contents)

    def test_restream_client_normalizes_live_event_and_destinations(self):
        client = RestreamClient({"enabled": True, "access_token": "token"})
        responses = {
            "/user/events/in-progress": [{"id": "event-1", "title": "Sunday Worship", "startedAt": 1, "destinations": [{"channelId": 12}]}],
            "/user/events/upcoming?scheduled=true": [],
            "/user/channels": {"channels": [{"id": 12, "displayName": "YouTube", "platformId": 5}, {"id": 13, "displayName": "Facebook", "platformId": 14}]},
            "/user/events/event-1/analytics/viewers": {"total": {"viewersPerMinute": [{"timestamp": 1, "viewers": 42}]}},
        }

        async def request(path):
            return responses[path]

        client._request = request
        status = asyncio.run(client.status())
        self.assertEqual(status["status"], "live")
        self.assertEqual(status["viewers"], 42)
        self.assertEqual(status["destinations"][0]["status"], "healthy")
        self.assertEqual(status["destinations"][1]["status"], "offline")


class DashboardTests(unittest.TestCase):
    def test_slug_is_normalized_and_validated(self):
        board = Dashboard(id="audio", name="Audio", slug="audio-board", widgets=[])
        self.assertEqual(board.slug, "audio-board")

    def test_background_color_is_normalized_and_validated(self):
        board = Dashboard(id="audio", name="Audio", slug="audio", background_color="#A12BC3", widgets=[])
        self.assertEqual(board.background_color, "#a12bc3")
        with self.assertRaises(ValueError):
            Dashboard(id="bad", name="Bad", slug="bad", background_color="red", widgets=[])


class PlanningCenterTests(unittest.TestCase):
    def test_consolidate_people_keeps_one_person_and_all_positions_in_plan_order(self):
        people = consolidate_people([
            {"id": "plan-1", "person_id": "caleb", "name": "Caleb Hines", "position": "Acoustic Guitar", "position_key": "band::acoustic guitar", "team_id": "band", "team_name": "Band", "photo": "", "status": "C"},
            {"id": "plan-2", "person_id": "caleb", "name": "Caleb Hines", "position": "Vocals", "position_key": "band::vocals", "team_id": "band", "team_name": "Band", "photo": "", "status": "C"},
        ])
        self.assertEqual(len(people), 1)
        self.assertEqual([position["name"] for position in people[0]["positions"]], ["Acoustic Guitar", "Vocals"])
        self.assertEqual(people[0]["position_keys"], ["band::acoustic guitar", "band::vocals"])

    def test_people_are_filtered_for_the_selected_service_time(self):
        people = consolidate_people([
            {"id": "john-row", "person_id": "john", "name": "John", "position": "Vox 1", "position_key": "band::vox 1", "team_id": "band", "team_name": "Band", "service_time_ids": ["early", "middle"]},
            {"id": "will-row", "person_id": "will", "name": "Will", "position": "Vox 1", "position_key": "band::vox 1", "team_id": "band", "team_name": "Band", "service_time_ids": ["late"]},
            {"id": "jane-row", "person_id": "jane", "name": "Jane", "position": "Vox 2", "position_key": "band::vox 2", "team_id": "band", "team_name": "Band", "service_time_ids": []},
        ])
        self.assertEqual([person["name"] for person in people_for_service_time(people, "early")], ["John", "Jane"])
        self.assertEqual([person["name"] for person in people_for_service_time(people, "late")], ["Will", "Jane"])

    def test_time_specific_secondary_position_stays_available_for_assignment_cards(self):
        people = consolidate_people([
            {"id": "will-vox2", "person_id": "will", "name": "Will", "position": "Vox 2", "position_key": "band::vox 2", "team_id": "band", "team_name": "Band", "service_time_ids": []},
            {"id": "will-vox1", "person_id": "will", "name": "Will", "position": "Vox 1", "position_key": "band::vox 1", "team_id": "band", "team_name": "Band", "service_time_ids": ["late"]},
        ])
        early = people_for_service_time(people, "early")[0]
        late = people_for_service_time(people, "late")[0]
        self.assertEqual(early["position_keys"], ["band::vox 2"])
        self.assertEqual(late["position_keys"], ["band::vox 2", "band::vox 1"])

    def test_manual_plan_wins(self):
        client = PlanningCenterClient({"open_days_before": 0, "open_hours_before": 0, "close_hours_after": 0})
        plans = [{"id": "1", "service_type_id": "a", "starts_at": "2030-01-01T00:00:00+00:00"}, {"id": "2", "service_type_id": "b", "starts_at": "2030-01-02T00:00:00+00:00"}]
        self.assertEqual(client.select_plan(plans, {"id": "2", "service_type_id": "b"})["id"], "2")

    def test_service_time_tracks_active_or_next_service(self):
        plan = {"times": [
            {"id": "early", "starts_at": "2030-01-06T13:30:00+00:00", "ends_at": "2030-01-06T14:30:00+00:00"},
            {"id": "late", "starts_at": "2030-01-06T16:00:00+00:00", "ends_at": "2030-01-06T17:00:00+00:00"},
        ]}
        self.assertEqual(selected_service_time(plan, datetime(2030, 1, 6, 12, 0, tzinfo=timezone.utc))["id"], "early")
        self.assertEqual(selected_service_time(plan, datetime(2030, 1, 6, 14, 45, tzinfo=timezone.utc))["id"], "late")
        self.assertEqual(selected_service_time(plan, datetime(2030, 1, 6, 16, 15, tzinfo=timezone.utc))["id"], "late")
        self.assertEqual(selected_service_time(plan, datetime(2030, 1, 6, 12, 0, tzinfo=timezone.utc), "late")["id"], "late")

    def test_timing_uses_service_specific_exclusions_and_start(self):
        plan = {
            "starts_at": "2030-01-06T13:30:00+00:00",
            "times": [
                {"id": "early", "starts_at": "2030-01-06T13:30:00+00:00", "ends_at": "2030-01-06T14:30:00+00:00"},
                {"id": "late", "starts_at": "2030-01-06T16:00:00+00:00", "ends_at": "2030-01-06T17:00:00+00:00"},
            ],
            "items": [
                {"id": "one", "title": "First service only", "length": 60, "service_times": [{"plan_time_id": "late", "exclude": True}]},
                {"id": "two", "title": "Welcome", "length": 120, "service_times": [{"plan_time_id": "late", "exclude": False}]},
            ],
        }
        timing = calculate_timing(plan, datetime(2030, 1, 6, 16, 1, tzinfo=timezone.utc))
        self.assertEqual(timing["service_time_id"], "late")
        self.assertEqual([item["id"] for item in timing["service_items"]], ["two"])
        self.assertEqual(timing["current_item"]["id"], "two")
        self.assertEqual(timing["current_item"]["starts_after"], 0)

    def test_pre_and_post_service_items_are_kept_and_anchored_around_service_start(self):
        plan = {
            "times": [{"id": "service", "starts_at": "2030-01-06T13:30:00+00:00", "ends_at": "2030-01-06T14:31:00+00:00"}],
            "items": [
                {"id": "pre-header", "title": "Pre-Service", "item_type": "header", "length": 0},
                {"id": "slides", "title": "Pre-Service Slides", "item_type": "item", "length": 0},
                {"id": "countdown", "title": "Countdown", "item_type": "item", "length": 300},
                {"id": "service-header", "title": "Service", "item_type": "header", "length": 0},
                {"id": "welcome", "title": "Welcome", "item_type": "item", "length": 60},
                {"id": "post-header", "title": "Post-Service", "item_type": "header", "length": 0},
                {"id": "reset", "title": "Room Reset", "item_type": "item", "length": 120},
            ],
        }
        timing = calculate_timing(plan, datetime(2030, 1, 6, 13, 30, 10, tzinfo=timezone.utc))
        self.assertEqual([item["id"] for item in timing["service_items"]], ["pre-header", "slides", "countdown", "service-header", "welcome", "post-header", "reset"])
        self.assertEqual([item["starts_after"] for item in timing["service_items"]], [-300, -300, -300, 0, 0, 60, 60])
        self.assertEqual(timing["current_item"]["id"], "welcome")

    def test_timing_finds_current_item(self):
        now = datetime.now(timezone.utc)
        plan = {"starts_at": (now - timedelta(seconds=90)).isoformat(), "planned_length": 180, "items": [{"id": "one", "title": "One", "starts_after": 0, "length": 60}, {"id": "two", "title": "Two", "starts_after": 60, "length": 120}]}
        timing = calculate_timing(plan, now)
        self.assertEqual(timing["current_item"]["id"], "two")
        self.assertEqual(timing["item_elapsed"], 30)

    def test_live_rehearsal_timing_overrides_a_future_service_clock(self):
        now = datetime(2030, 1, 5, 10, 2, tzinfo=timezone.utc)
        plan = {
            "starts_at": "2030-01-06T13:30:00+00:00",
            "times": [{"id": "early", "starts_at": "2030-01-06T13:30:00+00:00", "ends_at": "2030-01-06T14:30:00+00:00"}],
            "items": [
                {"id": "one", "title": "Opening", "length": 60, "service_times": [{"plan_time_id": "early", "live_start_at": "2030-01-05T10:00:00+00:00", "live_end_at": "2030-01-05T10:01:30+00:00"}]},
                {"id": "two", "title": "Message", "length": 60, "service_times": [{"plan_time_id": "early", "live_start_at": "2030-01-05T10:01:30+00:00", "live_end_at": None}]},
            ],
        }
        timing = calculate_timing(plan, now)
        self.assertEqual(timing["state"], "running")
        self.assertTrue(timing["live"])
        self.assertEqual(timing["current_item"]["id"], "two")
        self.assertEqual(timing["item_elapsed"], 30)
        self.assertEqual(timing["item_delta"], -30)
        self.assertEqual(timing["overall_delta"], 30)
        self.assertEqual(timing["service_elapsed"], 120)
        self.assertTrue(timing["rehearsal"])

    def test_live_timing_during_service_is_not_labeled_rehearsal(self):
        now = datetime(2030, 1, 6, 13, 45, tzinfo=timezone.utc)
        plan = {
            "times": [{"id": "service", "starts_at": "2030-01-06T13:30:00+00:00", "ends_at": "2030-01-06T14:30:00+00:00"}],
            "items": [
                {"id": "one", "title": "Opening", "length": 3600, "service_times": [{"plan_time_id": "service", "live_start_at": "2030-01-06T13:30:00+00:00", "live_end_at": None}]},
            ],
        }
        timing = calculate_timing(plan, now)
        self.assertTrue(timing["live"])
        self.assertFalse(timing["rehearsal"])

    def test_position_key_is_scoped_to_team(self):
        self.assertEqual(position_key("42", "  Vox 1 "), "42::vox 1")

    def test_item_leader_reads_direct_field_or_leader_note(self):
        self.assertEqual(item_leader({"song_leader": "Jordan Lee"}, []), "Jordan Lee")
        self.assertEqual(item_leader({}, [{"category_name": "Song Leader", "content": "Morgan Reed"}]), "Morgan Reed")
        self.assertEqual(item_leader({}, [{"category_name": "Item Leader", "content": "<p>Casey Rivers</p>"}]), "Casey Rivers")


class PlanningCenterCatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_media_tag_catalog_and_tagged_resources(self):
        client = PlanningCenterClient({"enabled": True, "application_id": "id", "secret": "secret"})

        async def fake_get_all(path, params=None):
            if path == "/tag_groups":
                return {"data": [{"id": "group-1", "attributes": {"name": "Documentation", "tags_for": "media"}}]}
            if path == "/tag_groups/group-1/tags":
                return {"data": [{"id": "tag-audio", "attributes": {"name": "Audio"}}]}
            self.assertEqual(path, "/media")
            self.assertEqual(params["where[media_tag_ids][]"], "tag-audio")
            return {
                "data": [{"id": "media-1", "attributes": {"title": "Audio Instructions", "image_url": "https://example.test/cover.png"}, "relationships": {"attachments": {"data": [{"type": "Attachment", "id": "file-1"}]}}}],
                "included": [{"type": "Attachment", "id": "file-1", "attributes": {"url": "https://example.test/audio.pdf", "filetype": "pdf", "display_name": "Audio.pdf"}, "links": {"self": "https://api.planningcenteronline.com/services/v2/media/media-1/attachments/file-1"}}],
            }

        client._get_all = fake_get_all
        groups = await client.media_tag_catalog()
        self.assertEqual(groups[0]["tags"][0]["name"], "Audio")
        resources = await client.media_for_tag("tag-audio")
        self.assertEqual(resources[0]["url"], "https://example.test/audio.pdf")
        self.assertEqual(resources[0]["source"], "Planning Center")
        self.assertEqual(resources[0]["inline_url"], "/api/producer/planning-center-media/media-1/content")
        self.assertEqual(resources[0]["filename"], "Audio.pdf")
        self.assertEqual(resources[0]["download_action_url"], "https://api.planningcenteronline.com/services/v2/media/media-1/attachments/file-1/open")
    async def test_catalog_groups_positions_by_team(self):
        client = PlanningCenterClient({"enabled": True, "application_id": "id", "secret": "secret", "service_type_ids": ["st-1"]})

        async def fake_get(path, params=None):
            if path == "/service_types":
                return {"data": [{"id": "st-1", "attributes": {"name": "Sunday"}}]}
            return {
                "data": [{"type": "TeamPosition", "id": "position-1", "attributes": {"name": "Vox 1"}, "relationships": {"team": {"data": {"type": "Team", "id": "team-1"}}}}],
                "included": [{"type": "Team", "id": "team-1", "attributes": {"name": "Band"}}],
            }

        client._get = fake_get
        catalog = await client.position_catalog()
        self.assertEqual(catalog[0]["name"], "Band")
        self.assertEqual(catalog[0]["positions"][0]["key"], "team-1::vox 1")

    async def test_plan_detail_uses_item_assignments_for_song_leaders(self):
        client = PlanningCenterClient({"enabled": True, "application_id": "id", "secret": "secret"})

        async def fake_get(path, params=None):
            if path.endswith("/team_members"):
                return {
                    "data": [{
                        "type": "PlanPerson",
                        "id": "plan-person-1",
                        "attributes": {"name": "Jordan Lee", "team_position_name": "Vox 1", "status": "C"},
                        "relationships": {
                            "person": {"data": {"type": "Person", "id": "person-1"}},
                            "team": {"data": {"type": "Team", "id": "team-1"}},
                        },
                    }],
                    "included": [
                        {"type": "Person", "id": "person-1", "attributes": {"photo_url": "https://example.test/jordan.jpg"}},
                        {"type": "Team", "id": "team-1", "attributes": {"name": "Band"}},
                    ],
                }
            self.assertTrue(path.endswith("/items"))
            self.assertIn("item_assignments", params["include"])
            return {
                "data": [{
                    "type": "Item",
                    "id": "item-1",
                    "attributes": {"title": "Song One", "item_type": "song", "length": 240, "sequence": 1},
                    "relationships": {
                        "item_assignments": {"data": [{"type": "ItemAssignment", "id": "assignment-1"}]},
                        "item_notes": {"data": [{"type": "ItemNote", "id": "note-1"}]},
                        "item_times": {"data": []},
                    },
                }],
                "included": [{
                    "type": "ItemAssignment",
                    "id": "assignment-1",
                    "relationships": {"assignable": {"data": {"type": "Person", "id": "person-1"}}},
                }, {"type": "ItemNote", "id": "note-1", "attributes": {"category_name": "Vocals", "content": "Testing"}}],
            }

        client._get = fake_get
        detail = await client.plan_detail({"id": "plan-1", "service_type_id": "type-1"})
        self.assertEqual(detail["people"][0]["person_id"], "person-1")
        self.assertEqual(detail["items"][0]["leader"], "Jordan Lee")
        self.assertEqual(detail["items"][0]["leader_person_ids"], ["person-1"])
        self.assertEqual(detail["items"][0]["note_fields"], [{"name": "Vocals", "content": "Testing"}])

    async def test_media_by_title_returns_the_planning_center_image(self):
        client = PlanningCenterClient({"enabled": True, "application_id": "id", "secret": "secret"})

        async def fake_get(path, params=None):
            self.assertEqual(path, "/media")
            self.assertEqual(params["where[title]"], "Icon")
            self.assertEqual(params["include"], "attachments")
            return {
                "data": [{
                    "type": "Media",
                    "id": "media-1",
                    "attributes": {
                        "title": "Icon",
                        "media_type": "video",
                        "image_url": "https://example.test/icon.png",
                        "updated_at": "2030-01-01T12:00:00Z",
                    },
                    "relationships": {"attachments": {"data": [{"type": "Attachment", "id": "attachment-1"}]}},
                }],
                "included": [{
                    "type": "Attachment",
                    "id": "attachment-1",
                    "attributes": {"content_type": "image/png", "filename": "Icon-white.png"},
                }],
            }

        client._get = fake_get
        media = await client.media_by_title("Icon")
        self.assertEqual(media["id"], "media-1")
        self.assertEqual(media["image_url"], "https://example.test/icon.png")

    async def test_live_status_reads_controller_and_current_item_time(self):
        client = PlanningCenterClient({"enabled": True, "application_id": "id", "secret": "secret"})

        async def fake_get(path, params=None):
            self.assertIn("/live", path)
            return {
                "data": [{"type": "Live", "id": "live-1", "attributes": {"can_control": True, "can_take_control": False}, "relationships": {"controller": {"data": {"type": "Person", "id": "person-1"}}, "current_item_time": {"data": {"type": "ItemTime", "id": "time-1"}}}}],
                "included": [{"type": "Person", "id": "person-1", "attributes": {"full_name": "Jordan Lee"}}, {"type": "ItemTime", "id": "time-1", "attributes": {"live_start_at": "2030-01-01T12:00:00Z", "live_end_at": None}, "relationships": {"item": {"data": {"type": "Item", "id": "item-2"}}}}],
            }

        client._get = fake_get
        live = await client.live_status({"id": "plan-1", "service_type_id": "type-1", "series_id": "series-1"})
        self.assertTrue(live["can_control"])
        self.assertTrue(live["has_control"])
        self.assertEqual(live["controller"], "Jordan Lee")
        self.assertEqual(live["current_item_id"], "item-2")
        self.assertEqual(live["current_live_start_at"], "2030-01-01T12:00:00Z")

    async def test_live_permission_without_a_controller_is_not_ownership(self):
        client = PlanningCenterClient({"enabled": True, "application_id": "id", "secret": "secret"})

        async def fake_get(path, params=None):
            return {"data": [{"type": "Live", "id": "live-1", "attributes": {"can_control": True, "can_take_control": True}, "relationships": {"controller": {"data": None}}}]}

        client._get = fake_get
        live = await client.live_status({"id": "plan-1", "service_type_id": "type-1"})
        self.assertTrue(live["can_control"])
        self.assertFalse(live["has_control"])

    async def test_planning_center_media_cache_downloads_and_prunes_removed_media(self):
        class Response:
            content = b"%PDF-1.7\nChurchBoard test"
            headers = {"content-type": "application/pdf"}

            def raise_for_status(self):
                return None

        class Downloader:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, url):
                self_url = url
                return Response()

        class Client:
            async def attachment_download_url(self, action_url):
                self.action_url = action_url
                return "https://objects.example.test/audio.pdf"

        with tempfile.TemporaryDirectory() as directory:
            cache = PlanningCenterMediaCache(Path(directory) / "state.json")
            client = Client()
            resource = {
                "id": "media-1", "title": "Audio Instructions", "filename": "Audio.pdf",
                "content_type": "application/pdf", "download_action_url": "https://api.example.test/attachment/open",
            }
            with patch("app.services.media_cache.httpx.AsyncClient", return_value=Downloader()):
                result = await cache.sync(client, {"tag-audio": [resource]})
            cached = cache.file_for("media-1")
            self.assertTrue(result["tag-audio"][0]["cached"])
            self.assertEqual(client.action_url, resource["download_action_url"])
            self.assertIsNotNone(cached)
            self.assertEqual(cached[0].read_bytes(), Response.content)
            await cache.sync(client, {})
            self.assertIsNone(cache.file_for("media-1"))


class ShureTests(unittest.TestCase):
    def test_shure_levels_are_clamped(self):
        self.assertEqual(percent("5", 5), 100)
        self.assertEqual(percent("-1", 5), 0)
        self.assertEqual(percent("bad", 5), 0)

    def test_unknown_battery_sentinel_does_not_look_full(self):
        self.assertEqual(battery_percent("5"), 100)
        self.assertIsNone(battery_percent("255"))
        self.assertIsNone(battery_percent("UNKN"))

    def test_unknown_transmitter_is_off_even_with_idle_rf(self):
        state = {"receiver_online": True, "tx_type": "UNKN", "battery_percent": 0, "rf": 37, "_battery_valid": False}
        self.assertFalse(transmitter_active(state))
        state.update({"tx_type": "QLXD2", "battery_percent": 80, "_battery_valid": True})
        self.assertTrue(transmitter_active(state))

    def test_configured_mics_on_same_ip_share_receiver(self):
        client = ShureClient({"enabled": True, "mics": [
            {"id": "blue", "name": "Blue", "host": "192.168.1.60", "channel": 1},
            {"id": "red", "name": "Red", "host": "192.168.1.60", "channel": 2},
        ]})
        receivers = client._configured_receivers()
        self.assertEqual(len(receivers), 1)
        self.assertEqual([mic["id"] for mic in receivers[0]["channel_configs"]], ["blue", "red"])

    def test_slxd_mic_uses_the_shure_tcp_receiver_and_keeps_its_model(self):
        client = ShureClient({"enabled": True, "mics": [
            {"id": "slxd-1", "name": "Pastor", "host": "192.168.1.70", "channel": 1, "model": "slxd"},
        ]})
        receiver = client._configured_receivers()[0]
        self.assertEqual(receiver["port"], 2202)
        self.assertEqual(receiver["model"], "slxd")


class ShureStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_tx_and_battery_sentinel_report_transmitter_off(self):
        class Reader:
            def __init__(self):
                self.done = False

            async def read(self, _size):
                if self.done:
                    return b""
                self.done = True
                return b"< REP 1 CHAN_NAME {VOX_1} >< REP 1 BATT_BARS {255} >< REP 1 TX_TYPE {UNKN} >< SAMPLE 1 ALL {0 42 0} >"

        class Writer:
            def write(self, _data):
                pass

            async def drain(self):
                pass

            def close(self):
                pass

            async def wait_closed(self):
                pass

        client = ShureClient({"enabled": True})
        receiver = {"id": "rack-a", "name": "Rack A", "host": "192.0.2.1", "port": 2202, "channels": 1}
        with patch("app.services.shure.asyncio.open_connection", AsyncMock(return_value=(Reader(), Writer()))):
            mic = (await client._receiver(receiver))[0]
        self.assertFalse(mic["online"])
        self.assertTrue(mic["receiver_online"])
        self.assertEqual(mic["battery_percent"], 0)
        self.assertEqual(mic["errors"], ["Transmitter off"])


class SennheiserTests(unittest.TestCase):
    def test_ssc_request_queries_dashboard_telemetry(self):
        request = ssc_request([1, 2])
        self.assertIsNone(request["m"]["rx1"]["rssi"])
        self.assertIsNone(request["mates"]["tx2"]["battery"]["gauge"])

    def test_ssc_response_normalizes_ew_dx_telemetry_and_alerts(self):
        response = {"device": {"product": "EW-DX EM 2", "firmware": "3.0.0"}, "rx1": {"name": "Vox", "frequency": 548250}, "m": {"rx1": {"rsqi": 15, "af": -30}}, "mates": {"tx1": {"mute": True, "battery": {"gauge": 9, "lifetime": 25}, "warnings": ["AfPeak"]}}}
        mic = parse_ssc_response(response, {"id": "ewdx", "name": "EW-DX"}, [1])[0]
        self.assertTrue(mic["online"])
        self.assertTrue(mic["muted"])
        self.assertEqual(mic["battery_percent"], 9)
        self.assertEqual(mic["rf"], 15)
        self.assertEqual(mic["frequency"], "548.250 MHz")
        self.assertIn("Low battery", mic["errors"])
        self.assertIn("Weak RF signal", mic["errors"])


class RuntimeAssignmentTests(unittest.TestCase):
    def test_live_mode_without_configured_mics_drops_seeded_demo_telemetry(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "state.json")
            data = store.load()
            data["settings"]["demo_mode"] = False
            data["settings"]["shure"] = {"enabled": False, "receivers": [], "mics": []}
            store.save(data)
            runtime = RuntimeService(store)
            self.assertTrue(runtime.state["mics"])
            state = asyncio.run(runtime.refresh(force=True))
            self.assertEqual(state["mics"], [])

    def test_position_key_maps_a_scheduled_person_to_named_mic(self):
        state = {
            "people": [{"name": "Jordan Lee", "position": "Vox 1", "position_key": "band::vox 1", "team_name": "Band"}],
            "mics": [{"id": "blue", "name": "Blue"}],
        }
        RuntimeService._apply_assignments(state, {"band::vox 1": "blue"})
        self.assertEqual(state["mics"][0]["assignment"]["name"], "Jordan Lee")

    def test_each_position_mic_maps_to_the_same_consolidated_person(self):
        person = {"person_id": "caleb", "name": "Caleb Hines", "position": "Acoustic Guitar", "position_key": "band::acoustic guitar", "position_keys": ["band::acoustic guitar", "band::vocals"], "positions": [{"name": "Acoustic Guitar", "key": "band::acoustic guitar"}, {"name": "Vocals", "key": "band::vocals"}]}
        state = {"people": [person], "mics": [{"id": "instrument", "name": "Instrument"}, {"id": "vocal", "name": "Vocal"}]}
        RuntimeService._apply_assignments(state, {"band::acoustic guitar": "instrument", "band::vocals": "vocal"})
        self.assertEqual(state["mics"][0]["assignment"]["person_id"], "caleb")
        self.assertEqual(state["mics"][1]["assignment"]["person_id"], "caleb")
        self.assertEqual(state["mics"][0]["assignment"]["position_key"], "band::acoustic guitar")
        self.assertEqual(state["mics"][1]["assignment"]["position_key"], "band::vocals")

    def test_unfilled_mapped_position_keeps_its_filter_key(self):
        state = {"people": [], "mics": [{"id": "blue", "name": "Blue"}]}
        RuntimeService._apply_assignments(state, {"band::vox 1": "blue"})
        assignment = state["mics"][0]["assignment"]
        self.assertEqual(assignment["name"], "Unassigned")
        self.assertEqual(assignment["position_key"], "band::vox 1")
        self.assertEqual(assignment["team_id"], "band")

    def test_demo_state_populates_propresenter_playlist_previews(self):
        propresenter = RuntimeService.demo_state()["propresenter"]
        self.assertTrue(propresenter["playlist_presentations"])
        self.assertTrue(propresenter["playlist_presentations"][0]["slides"])
        self.assertEqual(propresenter["presentation_uuid"], propresenter["playlist_presentations"][0]["presentation_uuid"])

    def test_service_control_can_take_advance_and_release(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = RuntimeService(ConfigStore(Path(directory) / "state.json"))
            runtime.state = runtime.demo_state()
            taken = asyncio.run(runtime.service_control("take"))
            first_index = taken["service_control"]["index"]
            advanced = asyncio.run(runtime.service_control("next"))
            self.assertTrue(advanced["service_control"]["active"])
            self.assertGreaterEqual(advanced["service_control"]["index"], first_index)
            released = asyncio.run(runtime.service_control("release"))
            self.assertFalse(released["service_control"]["active"])

    def test_cached_services_live_timing_does_not_fall_back_between_polls(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = RuntimeService(ConfigStore(Path(directory) / "state.json"))
            service = {
                "id": "plan-1",
                "starts_at": "2030-01-01T12:00:00+00:00",
                "items": [
                    {"id": "one", "title": "Welcome", "length": 60, "starts_after": 0},
                    {"id": "two", "title": "Song", "length": 180, "starts_after": 60},
                ],
            }
            live = {"current_item_id": "two", "current_live_start_at": "2030-01-01T12:01:00+00:00"}
            runtime._remember_live(service, live)
            state = {"service": service, "timing": calculate_timing(service)}
            self.assertTrue(runtime._apply_cached_live_timing(state))
            self.assertEqual(state["timing"]["source"], "planning_center_live")
            self.assertEqual(state["timing"]["current_item"]["id"], "two")

    def test_rehearsal_clock_ignores_stale_live_times_and_tracks_forward_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = RuntimeService(ConfigStore(Path(directory) / "state.json"))
            service = {
                "id": "plan-1",
                "times": [{"id": "service", "starts_at": "2099-01-01T12:00:00+00:00", "ends_at": "2099-01-01T13:00:00+00:00"}],
                "items": [
                    {"id": "one", "title": "Welcome", "length": 60, "service_times": [{"plan_time_id": "service"}]},
                    {"id": "two", "title": "Song", "length": 180, "service_times": [{"plan_time_id": "service"}]},
                ],
            }
            state = {"service": service}
            first = {"current_item_id": "one", "current_item_time_id": "time-one", "current_live_start_at": "2000-01-01T12:00:00+00:00"}
            with patch("app.services.runtime.time.monotonic", return_value=1000):
                runtime._apply_live_timing(state, first)
            self.assertTrue(state["timing"]["rehearsal"])
            self.assertEqual(state["timing"]["item_elapsed"], 0)
            self.assertEqual(state["timing"]["overall_delta"], 0)

            second = {"current_item_id": "two", "current_item_time_id": "time-two", "current_live_start_at": "2000-01-01T12:01:00+00:00"}
            with patch("app.services.runtime.time.monotonic", return_value=1075):
                runtime._apply_live_timing(state, second)
            self.assertEqual(state["timing"]["current_item"]["id"], "two")
            self.assertEqual(state["timing"]["item_elapsed"], 0)
            self.assertEqual(state["timing"]["overall_delta"], 15)

    def test_propresenter_target_starts_rehearsal_timing_before_live_catches_up(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = RuntimeService(ConfigStore(Path(directory) / "state.json"))
            service = {
                "id": "plan-1",
                "times": [{"id": "service", "starts_at": "2099-01-01T12:00:00+00:00", "ends_at": "2099-01-01T13:00:00+00:00"}],
                "items": [
                    {"id": "welcome", "title": "Welcome", "length": 60, "service_times": [{"plan_time_id": "service"}]},
                    {"id": "grace", "title": "Good Grace", "length": 360, "service_times": [{"plan_time_id": "service"}]},
                ],
            }
            state = {"service": service, "timing": calculate_timing(service)}
            with patch("app.services.runtime.time.monotonic", return_value=1000):
                runtime._apply_provisional_rehearsal_target(
                    state,
                    service["items"][1],
                    {"presentation_uuid": "pp-good-grace"},
                )
            self.assertEqual(state["timing"]["current_item"]["id"], "grace")
            self.assertEqual(state["timing"]["source"], "propresenter_rehearsal")
            self.assertTrue(state["timing"]["rehearsal"])
            self.assertEqual(state["timing"]["item_elapsed"], 0)

            stale_live = {"current_item_id": "grace", "current_item_time_id": "pco-old", "current_live_start_at": "2000-01-01T12:00:00+00:00"}
            with patch("app.services.runtime.time.monotonic", return_value=1005):
                runtime._apply_live_timing(state, stale_live)
            self.assertEqual(state["timing"]["item_elapsed"], 5)

    def test_configured_unassigned_media_titles_are_collected_per_widget(self):
        data = {"dashboards": [{"widgets": [
            {"type": "assignments", "settings": {"use_planning_center_icon": True, "unassigned_media_title": "Alternate Logo"}},
            {"type": "assignments", "settings": {"use_planning_center_icon": False, "unassigned_media_title": "Disabled Logo"}},
        ]}]}
        self.assertEqual(RuntimeService._configured_media_titles(data), ["Alternate Logo", "Icon"])

    def test_livestream_sources_are_collected_from_enabled_widgets(self):
        data = {"secrets": {"livestream": {"main:streams:youtube": "secret"}}, "dashboards": [{"id": "main", "widgets": [{"id": "streams", "type": "livestreams", "settings": {"sources": [
            {"id": "youtube", "provider": "youtube", "enabled": True},
            {"id": "facebook", "provider": "facebook", "enabled": False},
        ]}}]}]}
        sources = RuntimeService._configured_stream_sources(data)
        self.assertEqual([item["id"] for item in sources], ["youtube"])
        self.assertEqual(sources[0]["api_token"], "secret")

    def test_livestream_status_payload_detection_is_explicit(self):
        self.assertTrue(RuntimeService._payload_is_live({"status": "broadcasting"}))
        self.assertTrue(RuntimeService._payload_is_live({"status": "LIVE_NOW"}))
        self.assertTrue(RuntimeService._payload_is_live({"isLive": True}))
        self.assertFalse(RuntimeService._payload_is_live({"status": "scheduled", "page": "live events"}))

    def test_livestream_metrics_keep_start_time_and_current_viewers(self):
        result = RuntimeService._stream_result(
            {"id": "youtube", "live": True, "status": "live"},
            {"liveStreamingDetails": {"actualStartTime": "2026-08-08T12:00:00Z", "concurrentViewers": "143"}},
        )
        self.assertEqual(result["started_at"], "2026-08-08T12:00:00Z")
        self.assertEqual(result["viewers"], 143)
        self.assertGreater(result["duration_seconds"], 0)

    def test_facebook_livestream_metrics_support_graph_api_fields(self):
        result = RuntimeService._stream_result(
            {"id": "facebook", "live": True, "status": "live"},
            {"data": [{"status": "LIVE", "creation_time": "2026-08-08T12:00:00Z", "live_views": "87"}]},
        )
        self.assertEqual(result["started_at"], "2026-08-08T12:00:00Z")
        self.assertEqual(result["viewers"], 87)

    def test_facebook_page_token_uses_official_live_video_status(self):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"data": [{"status": "LIVE", "creation_time": "2026-08-08T12:00:00Z", "live_views": 41}]}

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, url, **kwargs):
                self.url = url
                self.params = kwargs.get("params") or {}
                return Response()

        fake = Client()
        with patch("app.services.runtime.httpx.AsyncClient", return_value=fake):
            statuses = asyncio.run(RuntimeService._livestream_statuses([{
                "id": "facebook",
                "provider": "facebook",
                "label": "Facebook",
                "channel_url": "https://www.facebook.com/yourchurch",
                "api_token": "page-token",
            }], {}, []))
        self.assertEqual(fake.url, "https://graph.facebook.com/yourchurch/live_videos")
        self.assertEqual(fake.params["broadcast_status"], "LIVE")
        self.assertTrue(statuses[0]["live"])
        self.assertEqual(statuses[0]["viewers"], 41)

    def test_propresenter_title_matching_prefers_song_and_forward_duplicate(self):
        items = [
            {"id": "1", "title": "Welcome", "item_type": "item"},
            {"id": "2", "title": "Great I Am", "item_type": "song"},
            {"id": "3", "title": "Message", "item_type": "item"},
            {"id": "4", "title": "Great I Am", "item_type": "song"},
        ]
        matched = RuntimeService._match_presentation_item("GREAT—I AM!", items, "3", {"songs_only": True, "match_mode": "exact"})
        self.assertEqual(matched["id"], "4")

    def test_active_plan_detail_refreshes_between_catalog_scans(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "state.json")
            data = store.load()
            data["settings"]["demo_mode"] = False
            data["settings"]["planning_center"].update({
                "enabled": True,
                "application_id": "app",
                "secret": "secret",
                "refresh_seconds": 60,
                "detail_refresh_seconds": 5,
            })
            store.save(data)
            runtime = RuntimeService(store)
            old_service = {
                "id": "plan",
                "service_type_id": "type",
                "starts_at": "2099-01-01T12:00:00+00:00",
                "items": [{"id": "welcome", "title": "Welcome", "length": 60}],
                "people": [],
            }
            new_service = {
                **old_service,
                "items": [
                    *old_service["items"],
                    {"id": "new-song", "title": "Lord I Lift Your Name On High", "length": 197},
                ],
            }
            runtime.state = {"service": old_service, "people": [], "plans": [old_service]}
            runtime._last_refresh["planning_center"] = 100
            runtime._last_refresh["planning_center_detail"] = 100

            class FakePlanningCenterClient:
                configured = True

                def __init__(self, _settings):
                    pass

                async def plan_detail(self, plan):
                    self.plan = plan
                    return new_service

            async def refresh_twice():
                await runtime.refresh()
                await asyncio.sleep(0)
                return await runtime.refresh()

            with patch("app.services.runtime.PlanningCenterClient", FakePlanningCenterClient), patch("app.services.runtime.time.monotonic", return_value=106):
                state = asyncio.run(refresh_twice())

            self.assertEqual([item["id"] for item in state["service"]["items"]], ["welcome", "new-song"])
            self.assertEqual([item["id"] for item in state["timing"]["service_items"]], ["welcome", "new-song"])


class ProPresenterLiveSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_stable_presentation_takes_control_and_advances_live(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = RuntimeService(ConfigStore(Path(directory) / "state.json"))
            state = {
                "service": {"id": "plan", "service_type_id": "type", "series_id": "series", "starts_at": "2030-01-01T12:00:00+00:00", "items": [
                    {"id": "1", "title": "Welcome", "item_type": "item", "length": 60, "starts_after": 0},
                    {"id": "2", "title": "Song One", "item_type": "song", "length": 120, "starts_after": 60},
                    {"id": "3", "title": "Song Two", "item_type": "song", "length": 120, "starts_after": 180},
                ]},
                "propresenter": {"connected": True, "title": "Song Two", "presentation_uuid": "pp-3"},
                "timing": {"current_item": {"id": "1"}},
            }

            class FakeLiveClient:
                configured = True

                def __init__(self):
                    self.actions = []
                    self.current = "1"
                    self.control = False

                async def live_status(self, _plan, create=False):
                    return {"id": "live", "series_id": "series", "can_control": True, "can_take_control": True, "has_control": self.control, "current_item_id": self.current, "current_live_start_at": "2030-01-01T12:00:00Z"}

                async def live_action(self, _plan, _live, action):
                    self.actions.append(action)
                    if action == "toggle_control":
                        self.control = True
                    elif action == "go_to_next_item":
                        self.current = str(int(self.current) + 1)
                    return await self.live_status(_plan)

            client = FakeLiveClient()
            settings = {"enabled": True, "auto_take_control": True, "songs_only": True, "allow_previous": False, "match_mode": "exact", "stable_seconds": 0, "refresh_seconds": 2}
            await runtime._sync_propresenter_live(state, client, settings, 10)
            await runtime._sync_propresenter_live(state, client, settings, 10.1)
            self.assertEqual(client.actions, ["toggle_control", "go_to_next_item", "go_to_next_item"])
            self.assertEqual(state["planning_center_live"]["state"], "synced")
            self.assertEqual(state["timing"]["current_item"]["id"], "3")
            self.assertEqual(state["timing"]["source"], "planning_center_live")

    async def test_empty_live_session_advances_from_before_first_item(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = RuntimeService(ConfigStore(Path(directory) / "state.json"))
            state = {
                "service": {"id": "plan", "service_type_id": "type", "starts_at": "2030-01-01T12:00:00+00:00", "items": [
                    {"id": "1", "title": "Welcome", "item_type": "item", "length": 60, "starts_after": 0},
                    {"id": "2", "title": "Song", "item_type": "song", "length": 120, "starts_after": 60},
                ]},
                "propresenter": {"connected": True, "title": "Song", "presentation_uuid": "pp-song"},
                "timing": {"current_item": {"id": "1"}},
            }

            class EmptyLiveClient:
                configured = True

                def __init__(self):
                    self.actions = []
                    self.position = -1
                    self.control = False

                async def live_status(self, _plan, create=False):
                    current = str(self.position + 1) if self.position >= 0 else ""
                    return {"id": "live", "can_control": True, "can_take_control": True, "has_control": self.control, "current_item_id": current, "next_item_id": ""}

                async def live_action(self, _plan, _live, action):
                    self.actions.append(action)
                    if action == "toggle_control":
                        self.control = True
                    elif action == "go_to_next_item":
                        self.position += 1
                    return await self.live_status(_plan)

            client = EmptyLiveClient()
            settings = {"enabled": True, "auto_take_control": True, "songs_only": True, "allow_previous": False, "match_mode": "exact", "stable_seconds": 0, "refresh_seconds": 2}
            await runtime._sync_propresenter_live(state, client, settings, 10)
            await runtime._sync_propresenter_live(state, client, settings, 10.1)
            self.assertEqual(client.actions, ["toggle_control", "go_to_next_item", "go_to_next_item"])
            self.assertEqual(state["planning_center_live"]["state"], "synced")
            self.assertEqual(state["timing"]["current_item"]["id"], "2")

    async def test_linked_pco_item_continuously_corrects_live_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = RuntimeService(ConfigStore(Path(directory) / "state.json"))
            state = {
                "service": {"id": "plan", "service_type_id": "type", "starts_at": "2030-01-01T12:00:00+00:00", "items": [
                    {"id": "1", "title": "Good Grace", "item_type": "song", "length": 120, "starts_after": 0},
                    {"id": "2", "title": "Welcome", "item_type": "item", "length": 60, "starts_after": 120},
                ]},
                "propresenter": {"connected": True, "title": "Good Grace", "service_item_title": "Good Grace", "service_item_index": 0, "service_item_is_pco": True, "presentation_uuid": "pp-good-grace"},
                "timing": {"current_item": {"id": "1"}},
            }

            class DriftClient:
                configured = True

                def __init__(self):
                    self.current = "1"
                    self.actions = []

                async def live_status(self, _plan, create=False):
                    return {"id": "live", "can_control": True, "can_take_control": True, "has_control": True, "current_item_id": self.current}

                async def live_action(self, _plan, _live, action):
                    self.actions.append(action)
                    if action == "go_to_previous_item":
                        self.current = "1"
                    return await self.live_status(_plan)

            client = DriftClient()
            settings = {"enabled": True, "auto_take_control": True, "songs_only": True, "allow_previous": False, "match_mode": "exact", "stable_seconds": 0, "refresh_seconds": 2}
            await runtime._sync_propresenter_live(state, client, settings, 10)
            await runtime._sync_propresenter_live(state, client, settings, 10.1)
            client.current = "2"
            await runtime._sync_propresenter_live(state, client, settings, 10.7)
            self.assertEqual(client.actions, ["go_to_previous_item"])
            self.assertEqual(state["planning_center_live"]["state"], "synced")
            self.assertEqual(state["timing"]["current_item"]["id"], "1")

    async def test_same_presentation_retries_after_live_action_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = RuntimeService(ConfigStore(Path(directory) / "state.json"))
            state = {
                "service": {"id": "plan", "service_type_id": "type", "starts_at": "2030-01-01T12:00:00+00:00", "items": [
                    {"id": "1", "title": "Welcome", "item_type": "item", "length": 60, "starts_after": 0},
                    {"id": "2", "title": "Message", "item_type": "item", "length": 120, "starts_after": 60},
                ]},
                "propresenter": {"connected": True, "title": "John 1:1-3", "service_item_title": "Message", "service_item_is_pco": True, "presentation_uuid": "pp-message"},
                "timing": {"current_item": {"id": "1"}},
            }

            class FlakyLiveClient:
                configured = True

                def __init__(self):
                    self.attempts = 0
                    self.current = "1"

                async def live_status(self, _plan, create=False):
                    return {"id": "live", "can_control": True, "can_take_control": True, "has_control": True, "current_item_id": self.current, "current_live_start_at": "2030-01-01T12:00:00Z"}

                async def live_action(self, _plan, _live, action):
                    self.attempts += 1
                    if self.attempts == 1:
                        raise ValueError("temporary LIVE ownership failure")
                    self.current = "2"
                    return await self.live_status(_plan)

            client = FlakyLiveClient()
            settings = {"enabled": True, "auto_take_control": True, "songs_only": False, "allow_previous": False, "match_mode": "exact", "stable_seconds": 0, "refresh_seconds": 2}
            await runtime._sync_propresenter_live(state, client, settings, 10)
            await runtime._sync_propresenter_live(state, client, settings, 10.1)
            self.assertEqual(state["planning_center_live"]["state"], "error")
            await runtime._sync_propresenter_live(state, client, settings, 10.2)
            self.assertEqual(client.attempts, 2)
            self.assertEqual(state["planning_center_live"]["state"], "synced")
            self.assertEqual(state["timing"]["current_item"]["id"], "2")

    async def test_manual_controls_use_services_live_when_automation_is_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "state.json")
            data = store.load()
            data["settings"]["demo_mode"] = False
            data["settings"]["planning_center"].update({"enabled": True, "application_id": "id", "secret": "secret"})
            data["settings"]["planning_center"]["live_from_propresenter"]["enabled"] = True
            store.save(data)
            runtime = RuntimeService(store)
            runtime.state = {"service": {"id": "plan", "service_type_id": "type", "starts_at": "2030-01-01T12:00:00+00:00", "items": [
                {"id": "1", "title": "First", "item_type": "item", "length": 60, "starts_after": 0},
                {"id": "2", "title": "Second", "item_type": "item", "length": 60, "starts_after": 60},
            ]}, "timing": {"current_item": {"id": "1"}}}

            class FakeClient:
                async def live_status(self, _plan, create=False):
                    return {"id": "live", "can_control": True, "can_take_control": True, "has_control": True, "current_item_id": "1", "current_live_start_at": "2030-01-01T12:00:00Z"}

                async def live_action(self, _plan, _live, action):
                    self.action = action
                    return {**_live, "current_item_id": "2", "current_live_start_at": "2030-01-01T12:01:00Z"}

            client = FakeClient()
            with patch("app.services.runtime.PlanningCenterClient", return_value=client):
                state = await runtime.service_control("next")
            self.assertEqual(client.action, "go_to_next_item")
            self.assertEqual(state["timing"]["current_item"]["id"], "2")
            self.assertEqual(state["planning_center_live"]["message"], "Services LIVE was updated manually")


class ProPresenterTests(unittest.TestCase):
    def test_planning_center_playlist_context_reads_item_title_and_index(self):
        context = ProPresenterClient._playlist_context({"presentation": {
            "playlist": {"uuid": "playlist-1", "name": "August 2, 2026"},
            "item": {"uuid": "item-1", "name": "Good Grace", "index": 2},
            "playlist_item": {"id": {"name": "Good Grace - local file", "index": 2}, "is_pco": True},
        }})
        self.assertTrue(context["service_item_is_pco"])
        self.assertEqual(context["service_item_title"], "Good Grace")
        self.assertEqual(context["service_item_index"], 2)
        self.assertEqual(context["playlist_name"], "August 2, 2026")

    def test_playlist_context_uses_valid_linked_index_when_item_index_is_sentinel(self):
        context = ProPresenterClient._playlist_context({"presentation": {
            "playlist": {"uuid": "playlist-1", "name": "August 9, 2026"},
            "item": {"name": "John 1_1-3 (ASB)", "index": 4294967295},
            "playlist_item": {"id": {"name": "John 1_1-3 (ASB)", "index": 8}, "is_pco": True},
        }})
        self.assertEqual(context["service_item_index"], 8)

    def test_pco_playlist_index_beats_different_local_presentation_name(self):
        items = [
            {"id": "1", "title": "Great I Am", "item_type": "song"},
            {"id": "2", "title": "Center", "item_type": "song"},
            {"id": "3", "title": "Good Grace", "item_type": "song"},
        ]
        match = RuntimeService._match_presentation_item(
            "Good Grace - Hillsong United arrangement",
            items,
            "1",
            {"songs_only": True, "match_mode": "exact"},
            service_item_title="Good Grace",
            service_item_index=2,
            is_pco_item=True,
        )
        self.assertEqual(match["id"], "3")

    def test_pco_exact_title_beats_playlist_index_shifted_by_plan_headers(self):
        items = [
            {"id": "header", "title": "Service", "item_type": "header"},
            {"id": "good-grace", "title": "Good Grace", "item_type": "song"},
            {"id": "welcome", "title": "Welcome", "item_type": "item"},
            {"id": "another", "title": "Another In The Fire", "item_type": "song"},
        ]
        match = RuntimeService._match_presentation_item(
            "Another In The Fire",
            items,
            "header",
            {"songs_only": True, "match_mode": "exact"},
            service_item_title="Another In The Fire",
            service_item_index=1,
            is_pco_item=True,
        )
        self.assertEqual(match["id"], "another")

    def test_pco_playlist_index_matches_message_despite_scripture_filename(self):
        items = [
            {"id": "1", "title": "Good Grace", "item_type": "song"},
            {"id": "2", "title": "Message", "item_type": "item"},
        ]
        match = RuntimeService._match_presentation_item(
            "John 1_1-3 (ASB)",
            items,
            "1",
            {"songs_only": True, "match_mode": "exact"},
            service_item_title="John 1_1-3 (ASB)",
            service_item_index=1,
            is_pco_item=True,
        )
        self.assertEqual(match["id"], "2")

    def test_absolute_synced_playlist_index_matches_message_with_headers(self):
        items = [
            {"id": "pre", "title": "Pre-Service", "item_type": "header"},
            {"id": "slides", "title": "Pre-Service Slides", "item_type": "item"},
            {"id": "countdown", "title": "Countdown", "item_type": "item"},
            {"id": "service", "title": "Service", "item_type": "header"},
            {"id": "lord", "title": "Lord I Lift Your Name On High", "item_type": "song"},
            {"id": "fire", "title": "Another In The Fire", "item_type": "song"},
            {"id": "grace", "title": "Good Grace", "item_type": "song"},
            {"id": "welcome", "title": "Welcome / Host Moment", "item_type": "item"},
            {"id": "message", "title": "Message", "item_type": "item"},
            {"id": "center", "title": "Center", "item_type": "item"},
        ]
        match = RuntimeService._match_presentation_item(
            "John 1_1-3 (ASB)",
            items,
            "welcome",
            {"songs_only": True, "match_mode": "exact"},
            service_item_title="John 1_1-3 (ASB)",
            service_item_index=8,
            service_item_index_is_absolute=True,
            is_pco_item=True,
        )
        self.assertEqual(match["id"], "message")

    def test_pco_playlist_index_ignores_headers_and_pre_service_rows(self):
        items = [
            {"id": "pre", "title": "Pre-Service", "item_type": "header"},
            {"id": "countdown", "title": "Countdown", "item_type": "item"},
            {"id": "service", "title": "Service", "item_type": "header"},
            {"id": "great", "title": "Great I Am", "item_type": "song", "service_times": [{"exclude": True}]},
            {"id": "center", "title": "Center", "item_type": "song"},
            {"id": "grace", "title": "Good Grace", "item_type": "song"},
            {"id": "welcome", "title": "Welcome / Host Moment", "item_type": "item"},
            {"id": "message", "title": "Message", "item_type": "item"},
            {"id": "fire", "title": "Another In The Fire", "item_type": "song"},
            {"id": "dismissal", "title": "Dismissal", "item_type": "item"},
        ]
        match = RuntimeService._match_presentation_item(
            "John 1_1-3 (ASB)",
            items,
            "center",
            {"songs_only": True, "match_mode": "exact"},
            service_item_title="John 1_1-3 (ASB)",
            service_item_index=4,
            is_pco_item=True,
        )
        self.assertEqual(match["id"], "message")

    def test_pco_pre_service_index_keeps_linked_rows_before_main_service(self):
        items = [
            {"id": "pre", "title": "Pre-Service", "item_type": "header"},
            {"id": "slides", "title": "Pre-Service Slides", "item_type": "item"},
            {"id": "countdown", "title": "Countdown", "item_type": "item"},
            {"id": "service", "title": "Service", "item_type": "header"},
            {"id": "great", "title": "Great I Am", "item_type": "song"},
            {"id": "center", "title": "Center", "item_type": "song"},
        ]
        match = RuntimeService._match_presentation_item(
            "Announcements",
            items,
            "center",
            {"songs_only": True, "match_mode": "exact"},
            service_item_title="Announcements",
            service_item_index=1,
            is_pco_item=True,
        )
        self.assertEqual(match["id"], "slides")

    def test_strong_title_fallback_can_match_a_non_song_item(self):
        items = [
            {"id": "1", "title": "Good Grace", "item_type": "song"},
            {"id": "2", "title": "Message", "item_type": "item"},
        ]
        match = RuntimeService._match_presentation_item(
            "Sunday Message",
            items,
            "1",
            {"songs_only": True, "match_mode": "exact"},
        )
        self.assertEqual(match["id"], "2")

    def test_exact_title_mode_ignores_common_presentation_suffix(self):
        items = [{"id": "1", "title": "Another In The Fire", "item_type": "song"}]
        match = RuntimeService._match_presentation_item(
            "Another In The Fire - Hillsong UNITED [PCO]",
            items,
            "",
            {"songs_only": True, "match_mode": "exact"},
        )
        self.assertEqual(match["id"], "1")

    def test_grouped_cues_and_slide_notes_are_read(self):
        presentation = {"groups": [{"cues": [{"slide": {"notes": "Watch the director"}}]}]}
        cues = ProPresenterClient._cues(presentation)
        self.assertEqual(ProPresenterClient._notes(cues[0]), "Watch the director")

    def test_group_names_and_colors_follow_each_cue(self):
        presentation = {
            "name": "Build My Life",
            "groups": [
                {
                    "name": "Verse 1",
                    "color": {"red": 1, "green": 0.2, "blue": 0.1, "alpha": 1},
                    "slides": [{"text": "Worthy of every song", "label": "Acoustic", "color": "#ffffff"}, {"text": "Worthy of all the praise"}],
                },
                {
                    "id": {"name": "Chorus", "color": "0.2 0.8 0.4 1"},
                    "cues": [{"text": "Holy, there is no one like You"}],
                },
            ],
        }
        entries = ProPresenterClient._cue_entries(presentation)
        self.assertEqual(ProPresenterClient._presentation_title(presentation), "Build My Life")
        self.assertEqual([entry["part"] for entry in entries], ["Verse 1", "Verse 1", "Chorus"])
        self.assertEqual(entries[0]["color"], "rgba(255, 51, 26, 1)")
        self.assertEqual(entries[2]["color"], "rgba(51, 204, 102, 1)")

    def test_active_arrangement_repeats_groups_in_live_order(self):
        presentation = {
            "groups": [
                {"uuid": "blank", "name": "Blank", "slides": [{"label": "Background.mp4", "text": ""}]},
                {"uuid": "chorus", "name": "Chorus 1", "slides": [{"text": "Chorus line"}]},
                {"uuid": "verse", "name": "Verse 2", "slides": [{"text": "Verse first"}, {"text": "Verse last"}]},
                {"uuid": "bridge", "name": "Bridge", "slides": [{"text": "Bridge line"}]},
            ],
            "arrangements": [{"id": {"uuid": "arrangement", "index": 0}, "groups": ["verse", "chorus", "bridge", "chorus"], "total_cues": 5}],
        }
        entries = ProPresenterClient._presentation_cue_entries(presentation)
        self.assertEqual([entry["part"] for entry in entries], ["Verse 2", "Verse 2", "Chorus 1", "Bridge", "Chorus 1"])
        self.assertEqual([entry["_thumbnail_index"] for entry in entries], [2, 3, 1, 4, 1])
        current, next_position = ProPresenterClient._cue_positions(entries, {"text": "Verse last"}, {"text": "Chorus line"}, 1)
        self.assertEqual((current, next_position), (1, 2))
        self.assertEqual(ProPresenterClient._cue_total({"presentation_index": {"total_cues": 5}}, len(entries)), 5)

    def test_nested_live_presentation_index_is_read(self):
        payload = {"presentation_index": {"index": 4, "presentation_id": {"uuid": "ABC-123"}}}
        self.assertEqual(ProPresenterClient._index(payload), 4)

    def test_thumbnail_url_uses_presentation_and_live_cue(self):
        presentation = {"id": {"uuid": "ABC-123", "name": "Welcome"}}
        uuid = ProPresenterClient._presentation_uuid(presentation)
        self.assertEqual(uuid, "ABC-123")
        self.assertEqual(
            ProPresenterClient._thumbnail_url(uuid, 3, "SLIDE-456"),
            "/api/integrations/propresenter/thumbnail/ABC-123/3?revision=SLIDE-456",
        )

    def test_presentation_title_and_hex_color_support_nested_ids(self):
        self.assertEqual(ProPresenterClient._presentation_title({"id": {"name": "Welcome"}}), "Welcome")
        self.assertEqual(ProPresenterClient._color("65a9ff"), "#65a9ff")
        self.assertEqual(ProPresenterClient._color("not-a-color"), "")

    def test_live_countdown_text_is_extracted_from_slide_text(self):
        self.assertEqual(ProPresenterClient._countdown_text("Service begins in\n05:24"), "05:24")
        self.assertEqual(ProPresenterClient._countdown_text("-00:00:02.00"), "-00:00:02.00")
        self.assertEqual(ProPresenterClient._countdown_text("John 3:16"), "")

    def test_video_transport_status_includes_progress(self):
        class Response:
            is_success = True

            def __init__(self, value):
                self.value = value

            def json(self):
                return self.value

        status = ProPresenterClient._transport_status(
            Response({"is_playing": True, "uuid": "VIDEO-1", "name": "Countdown", "audio_only": False, "duration": 300}),
            Response(42.5),
        )
        self.assertEqual(status["media"]["position"], 42.5)
        self.assertEqual(status["media"]["duration"], 300)

    def test_timer_element_uses_running_propresenter_timer(self):
        timers = [
            {"name": "PreShow Countdown", "time": "05:00:00", "state": "stopped"},
            {"name": "Segment Countdown", "time": "00:04:17", "state": "running"},
        ]
        value = ProPresenterClient._timer_for_slide(
            timers,
            "754:56",
            "Countdown",
            {"label": "Pre-Service 5:00"},
        )
        self.assertEqual(value, "00:04:17")

    def test_video_remaining_time_is_not_a_lyric_timer(self):
        timers = [{"name": "Segment Countdown", "time": "00:04:17", "state": "running"}]
        value = ProPresenterClient._timer_for_slide(
            timers,
            "Lord I lift Your name on high\nLord I love to sing Your praises",
            "Lord I Lift Your Name On High",
            {"label": "Verse"},
        )
        self.assertEqual(value, "")


class ProPresenterPollingTests(unittest.IsolatedAsyncioTestCase):
    async def test_thumbnail_route_converts_zero_based_cue_to_one_based_number(self):
        class FakeResponse:
            content = b"jpeg"
            headers = {"content-type": "image/jpeg"}

            def raise_for_status(self):
                return None

        class FakeHttp:
            def __init__(self):
                self.url = ""

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, url, **_kwargs):
                self.url = url
                return FakeResponse()

        fake = FakeHttp()
        client = ProPresenterClient({"enabled": True, "host": "127.0.0.1", "port": 50001})
        with patch("app.services.propresenter.httpx.AsyncClient", return_value=fake):
            content, media_type = await client.thumbnail("ABC-123", 3)
        self.assertEqual(content, b"jpeg")
        self.assertEqual(media_type, "image/jpeg")
        self.assertTrue(fake.url.endswith("/v1/presentation/ABC-123/thumbnail/4"))

    async def test_active_playlist_context_drives_live_match_when_focus_is_elsewhere(self):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload
                self.status_code = 200
                self.is_success = True

            def json(self):
                return self.payload

            def raise_for_status(self):
                return None

        class FakeHttp:
            async def get(self, url):
                if url.endswith("/v1/status/slide"):
                    return FakeResponse({"current": {"text": "In the beginning"}, "next": {"text": "The Word was with God"}})
                if url.endswith("/v1/presentation/slide_index"):
                    return FakeResponse(0)
                if url.endswith("/v1/presentation/active"):
                    return FakeResponse({"presentation": {"id": {"uuid": "MESSAGE-PRES", "name": "John 1:1-3 (ASB)"}}})
                if url.endswith("/v1/playlist/active"):
                    return FakeResponse({"presentation": {"playlist": {"uuid": "PLAN", "name": "Sunday"}, "item": {"name": "Message", "index": 3}, "playlist_item": {"is_pco": True}}})
                if url.endswith("/v1/playlist/focused"):
                    return FakeResponse({"presentation": {"playlist": {"uuid": "PLAN", "name": "Sunday"}, "item": {"name": "Lord I Lift Your Name On High", "index": 1}, "playlist_item": {"is_pco": True}}})
                if url.endswith("/v1/playlist/PLAN"):
                    return FakeResponse({"items": []})
                if url.endswith("/v1/presentation/MESSAGE-PRES"):
                    return FakeResponse({"id": {"uuid": "MESSAGE-PRES", "name": "John 1:1-3 (ASB)"}, "groups": [{"name": "Message", "slides": [{"text": "In the beginning"}, {"text": "The Word was with God"}]}]})
                return FakeResponse({})

        client = ProPresenterClient({"enabled": True, "host": "127.0.0.1", "port": 53528})
        client._client = FakeHttp()
        status = await client.status()
        self.assertEqual(status["service_item_title"], "Message")
        self.assertEqual(status["service_item_index"], 3)
        self.assertTrue(status["service_item_is_pco"])
        self.assertEqual(status["playlist_name"], "Sunday")

    async def test_focused_synced_playlist_row_marks_message_index_as_absolute(self):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload
                self.status_code = 200
                self.is_success = True

            def json(self):
                return self.payload

            def raise_for_status(self):
                return None

        class FakeHttp:
            async def get(self, url):
                if url.endswith("/v1/status/slide"):
                    return FakeResponse({"current": {"text": "In the beginning"}, "next": {"text": "The Word was with God"}})
                if url.endswith("/v1/presentation/slide_index"):
                    return FakeResponse(0)
                if url.endswith("/v1/presentation/active"):
                    return FakeResponse({"presentation": {"id": {"uuid": "MESSAGE-PRES", "name": "John 1_1-3 (ASB)"}}})
                if url.endswith("/v1/playlist/active"):
                    return FakeResponse({"presentation": {"playlist": None, "item": None, "playlist_item": None}})
                if url.endswith("/v1/playlist/focused"):
                    return FakeResponse({"presentation": {
                        "playlist": {"uuid": "PLAN", "name": "August 9, 2026", "index": 2},
                        "item": {"name": "John 1_1-3 (ASB)", "index": 4294967295},
                        "playlist_item": {"id": {"name": "John 1_1-3 (ASB)", "index": 8}, "is_pco": True},
                    }})
                if url.endswith("/v1/playlist/PLAN"):
                    return FakeResponse({"items": [
                        {"type": "presentation", "name": "Lord I Lift Your Name On High", "index": 4, "is_pco": True, "presentation_info": {"presentation_uuid": "LORD-PRES"}},
                        {"type": "presentation", "name": "John 1_1-3 (ASB)", "index": 8, "is_pco": True, "presentation_info": {"presentation_uuid": "MESSAGE-PRES"}},
                    ]})
                if url.endswith("/v1/presentation/MESSAGE-PRES"):
                    return FakeResponse({"id": {"uuid": "MESSAGE-PRES", "name": "John 1_1-3 (ASB)"}, "groups": [{"name": "Message", "slides": [{"text": "In the beginning"}]}]})
                if url.endswith("/v1/presentation/LORD-PRES"):
                    return FakeResponse({"id": {"uuid": "LORD-PRES", "name": "Lord I Lift Your Name On High"}, "groups": []})
                return FakeResponse({})

        client = ProPresenterClient({"enabled": True, "host": "127.0.0.1", "port": 53528})
        client._client = FakeHttp()
        status = await client.status()
        self.assertEqual(status["service_item_index"], 8)
        self.assertTrue(status["service_item_index_is_absolute"])
        self.assertTrue(status["service_item_is_pco"])

    async def test_active_presentation_arrangement_is_not_replaced_by_library_details(self):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload
                self.status_code = 200
                self.is_success = True

            def json(self):
                return self.payload

            def raise_for_status(self):
                return None

        live_groups = [{"uuid": "live", "name": "Chorus", "slides": [{"text": "Live chorus"}]}]
        library_groups = [{"uuid": "library", "name": "Verse", "slides": [{"text": "Library verse"}]}]

        class FakeHttp:
            async def get(self, url):
                if url.endswith("/v1/status/slide"):
                    return FakeResponse({"current": {"text": "Live chorus"}, "next": {}})
                if url.endswith("/v1/presentation/slide_index"):
                    return FakeResponse(0)
                if url.endswith("/v1/presentation/active"):
                    return FakeResponse({"presentation": {"id": {"uuid": "LORD", "name": "Lord I Lift Your Name On High"}, "groups": live_groups}})
                if url.endswith("/v1/presentation/LORD"):
                    return FakeResponse({"id": {"uuid": "LORD", "name": "Lord I Lift Your Name On High"}, "groups": library_groups})
                return FakeResponse({})

        client = ProPresenterClient({"enabled": True, "host": "127.0.0.1", "port": 53528})
        client._client = FakeHttp()
        status = await client.status()
        self.assertEqual([slide["text"] for slide in status["slides"]], ["Live chorus"])
        self.assertEqual(status["current"]["part"], "Chorus")

    async def test_playlist_loads_slides_for_every_presentation(self):
        class FakeResponse:
            def __init__(self, payload, status_code=200):
                self.payload = payload
                self.status_code = status_code
                self.is_success = 200 <= status_code < 300

            def json(self):
                return self.payload

            def raise_for_status(self):
                if not self.is_success:
                    raise RuntimeError(self.status_code)

        class FakeHttp:
            async def get(self, url):
                if url.endswith("/v1/status/slide"):
                    return FakeResponse({"current": {"text": "First song"}, "next": {"text": "First chorus"}})
                if url.endswith("/v1/presentation/slide_index"):
                    return FakeResponse(0)
                if url.endswith("/v1/presentation/active"):
                    return FakeResponse({"presentation": {"id": {"uuid": "PRES-1", "name": "Song One"}}})
                if url.endswith("/v1/playlist/active") or url.endswith("/v1/playlist/focused"):
                    return FakeResponse({"presentation": {"playlist": {"uuid": "PLAYLIST-1", "name": "Sunday"}, "item": {"name": "Song One", "index": 0}}})
                if url.endswith("/v1/playlist/PLAYLIST-1"):
                    return FakeResponse({"items": [
                        {"id": {"index": 0, "name": "Song One"}, "type": "presentation", "presentation_info": {"presentation_uuid": "PRES-1"}},
                        {"id": {"index": 1, "name": "Song Two"}, "type": "presentation", "presentation_info": {"presentation_uuid": "PRES-2"}},
                    ]})
                if url.endswith("/v1/presentation/PRES-1"):
                    return FakeResponse({"id": {"uuid": "PRES-1", "name": "Song One"}, "groups": [{"name": "Verse", "slides": [{"text": "First song"}, {"text": "First chorus"}]}]})
                if url.endswith("/v1/presentation/PRES-2"):
                    return FakeResponse({"presentation": {"id": {"uuid": "PRES-2", "name": "Song Two"}, "groups": [{"name": "Verse", "slides": [{"text": "Second song"}]}, {"name": "Chorus", "slides": [{"text": "Second chorus"}]}]}})
                return FakeResponse({})

        client = ProPresenterClient({"enabled": True, "host": "127.0.0.1", "port": 53528})
        client._client = FakeHttp()
        status = await client.status()
        presentations = status["playlist_presentations"]
        self.assertEqual([item["title"] for item in presentations], ["Song One", "Song Two"])
        self.assertEqual([slide["text"] for slide in presentations[0]["slides"]], ["First song", "First chorus"])
        self.assertEqual([slide["text"] for slide in presentations[1]["slides"]], ["Second song", "Second chorus"])
        self.assertEqual(presentations[1]["slides"][1]["image_url"], "/api/integrations/propresenter/thumbnail/PRES-2/1")

    async def test_non_active_playlist_slide_targets_its_presentation(self):
        class FakeResponse:
            status_code = 200
            is_success = True

        class FakeHttp:
            def __init__(self):
                self.calls = []

            async def get(self, url):
                self.calls.append(url)
                return FakeResponse()

        client = ProPresenterClient({"enabled": True, "host": "127.0.0.1", "port": 53528})
        fake_http = FakeHttp()
        client._client = fake_http
        await client.trigger_playlist_slide(6, "6378A556-8122-44B9-AFC7-C3BC7AEE5301", 2)
        self.assertEqual(fake_http.calls, ["http://127.0.0.1:53528/v1/presentation/6378A556-8122-44B9-AFC7-C3BC7AEE5301/2/trigger"])

    async def test_playlist_cue_uses_live_active_presentation_route(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

        class FakeHttp:
            def __init__(self):
                self.calls = []

            async def get(self, url):
                self.calls.append(url)
                return FakeResponse()

        client = ProPresenterClient({"enabled": True, "host": "127.0.0.1", "port": 53528})
        fake_http = FakeHttp()
        client._client = fake_http
        await client.trigger_active_slide(4)
        self.assertEqual(fake_http.calls, ["http://127.0.0.1:53528/v1/presentation/active/4/trigger"])

    async def test_keyboard_navigation_uses_global_trigger_routes(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

        class FakeHttp:
            def __init__(self):
                self.calls = []

            async def get(self, url):
                self.calls.append(url)
                return FakeResponse()

        client = ProPresenterClient({"enabled": True, "host": "127.0.0.1", "port": 53528})
        fake_http = FakeHttp()
        client._client = fake_http
        await client.trigger_navigation("next")
        await client.trigger_navigation("previous")
        self.assertEqual(fake_http.calls, [
            "http://127.0.0.1:53528/v1/trigger/next",
            "http://127.0.0.1:53528/v1/trigger/previous",
        ])

    async def test_playlist_slide_trigger_targets_exact_presentation(self):
        class FakeResponse:
            is_success = True

            def raise_for_status(self):
                return None

        class FakeHttp:
            def __init__(self):
                self.calls = []

            async def get(self, url):
                self.calls.append(url)
                return FakeResponse()

        client = ProPresenterClient({"enabled": True, "host": "127.0.0.1", "port": 53528})
        fake_http = FakeHttp()
        client._client = fake_http
        await client.trigger_presentation_slide("6378A556-8122-44B9-AFC7-C3BC7AEE5301", 3)
        self.assertEqual(fake_http.calls, ["http://127.0.0.1:53528/v1/presentation/6378A556-8122-44B9-AFC7-C3BC7AEE5301/3/trigger"])

    async def test_playlist_slide_trigger_falls_back_to_active_for_pco_uuid(self):
        class FakeResponse:
            def __init__(self, status_code):
                self.status_code = status_code
                self.is_success = 200 <= status_code < 300

            def raise_for_status(self):
                if not self.is_success:
                    raise RuntimeError(self.status_code)

        class FakeHttp:
            def __init__(self):
                self.calls = []

            async def get(self, url):
                self.calls.append(url)
                return FakeResponse(404 if len(self.calls) == 1 else 200)

        client = ProPresenterClient({"enabled": True, "host": "127.0.0.1", "port": 53528})
        fake_http = FakeHttp()
        client._client = fake_http
        await client.trigger_presentation_slide("B45CCDD5-A432-48AA-A7F1-0C1E2C238D5A", 2)
        self.assertEqual(fake_http.calls, [
            "http://127.0.0.1:53528/v1/presentation/B45CCDD5-A432-48AA-A7F1-0C1E2C238D5A/2/trigger",
            "http://127.0.0.1:53528/v1/presentation/active/2/trigger",
        ])

    async def test_fast_poll_reuses_presentation_metadata_and_omits_raw_payload(self):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload
                self.is_success = True

            def json(self):
                return self.payload

            def raise_for_status(self):
                return None

        class FakeHttp:
            def __init__(self):
                self.calls = []

            async def get(self, url):
                self.calls.append(url)
                if url.endswith("/v1/status/slide"):
                    return FakeResponse({"current": {"text": "Current"}, "next": {"text": "Next"}})
                if url.endswith("/v1/presentation/slide_index"):
                    return FakeResponse(0)
                if url.endswith("/v1/presentation/active"):
                    return FakeResponse({"presentation": {"id": {"uuid": "PP-1", "name": "Song"}, "groups": [
                        {"name": "", "slides": [{"text": "", "label": "Background.mp4"}]},
                        {"name": "Verse", "slides": [{"text": "Current"}, {"text": "Next"}]},
                    ]}})
                return FakeResponse({"presentation": {"playlist": {"name": "Plan"}, "item": {"name": "Song", "index": 0}, "playlist_item": {"is_pco": True}}})

        client = ProPresenterClient({"enabled": True, "host": "127.0.0.1", "port": 50001})
        fake_http = FakeHttp()
        client._client = fake_http
        first = await client.status()
        second = await client.status()
        self.assertNotIn("presentation", first)
        self.assertEqual(second["current"]["part"], "Verse")
        self.assertEqual(second["current"]["image_url"], "/api/integrations/propresenter/thumbnail/PP-1/1")
        self.assertEqual(second["next"]["image_url"], "/api/integrations/propresenter/thumbnail/PP-1/2")
        self.assertEqual(sum(url.endswith("/v1/status/slide") for url in fake_http.calls), 2)
        self.assertEqual(sum(url.endswith("/v1/presentation/slide_index") for url in fake_http.calls), 2)
        self.assertEqual(sum(url.endswith("/v1/presentation/active") for url in fake_http.calls), 1)
        self.assertEqual(sum(url.endswith("/v1/playlist/active") for url in fake_http.calls), 1)


if __name__ == "__main__":
    unittest.main()
