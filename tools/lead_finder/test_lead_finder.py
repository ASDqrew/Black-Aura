import csv
import json
import io
import importlib.util
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("lead_finder", ROOT / "lead_finder.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class LeadFinderTests(unittest.TestCase):
    def test_city_extract_filters_businesses_and_location(self):
        import osmium
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.osm.pbf"
            with osmium.SimpleWriter(str(path)) as writer:
                writer.add_node(osmium.osm.mutable.Node(id=1, location=(37.6, 55.75), tags={"name": "Moscow Beauty", "shop": "beauty"}))
                writer.add_node(osmium.osm.mutable.Node(id=2, location=(30.3, 59.9), tags={"name": "Other city", "shop": "beauty"}))
                writer.add_node(osmium.osm.mutable.Node(id=3, location=(37.6, 55.75), tags={"name": "Bakery", "shop": "bakery"}))
            with patch.object(MODULE.urllib.request, "urlopen", return_value=io.BytesIO(path.read_bytes())):
                result = MODULE.fetch_city_extract(MODULE.MOSCOW_BBOX)
            self.assertEqual([item["id"] for item in result["elements"]], [1])

    def test_outage_uses_only_matching_saved_database(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "moscow.json"
            payload = {"elements": [{"type": "node", "id": 1, "tags": {"name": "Example"}}]}
            with patch.object(MODULE, "fetch_overpass", return_value=payload):
                fresh = MODULE.load_payload(None, MODULE.MOSCOW_BBOX, cache)
            self.assertEqual(fresh["lead_finder_status"], "live")
            with patch.object(MODULE, "fetch_overpass", side_effect=RuntimeError("outage")), patch.object(MODULE, "fetch_city_extract", side_effect=RuntimeError("extract outage")):
                saved = MODULE.load_payload(None, MODULE.MOSCOW_BBOX, cache)
                self.assertEqual(saved["lead_finder_status"], "cache")
                with self.assertRaises(ValueError):
                    MODULE.load_payload(None, "1,2,3,4", cache)
                with self.assertRaises(RuntimeError):
                    MODULE.load_payload(None, MODULE.MOSCOW_BBOX, Path(directory) / "missing.json")

    def test_unresearched_drafts_do_not_invent_page_problems(self):
        payload = MODULE.load_payload(ROOT / "fixtures" / "overpass_sample.json", MODULE.MOSCOW_BBOX)
        leads = MODULE.leads_from_payload(payload, 50)
        self.assertIn("форма и текстура", leads[0].message)
        self.assertIn("оформлением, окрашиванием", leads[1].message)
        self.assertIn("изгибах и объёмах", leads[2].message)
        for lead in leads:
            self.assertEqual(lead.research_status, "Нужен просмотр страницы")
            self.assertNotIn("приходится отдельно искать", lead.message)

    def test_research_requires_evidence_and_changes_offer(self):
        payload = MODULE.load_payload(ROOT / "fixtures" / "overpass_sample.json", MODULE.MOSCOW_BBOX)
        leads = MODULE.leads_from_payload(payload, 50)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "research.json"
            profile = {"observation": "Вы предлагаете две техники.", "proposal": "сравнить техники", "benefit": "помочь выбрать услугу"}
            path.write_text(json.dumps({leads[0].source_id: profile}))
            with self.assertRaises(ValueError):
                MODULE.apply_research(leads, path)
            profile["source_url"] = "https://example.com/services"
            path.write_text(json.dumps({leads[0].source_id: profile}))
            MODULE.apply_research(leads, path)
            self.assertIn("Вы предлагаете две техники.", leads[0].message)
            self.assertEqual(leads[0].research_source, profile["source_url"])
            self.assertEqual(leads[1].research_status, "Нужен просмотр страницы")

    def test_booking_link_is_not_treated_as_standalone_site(self):
        lead = MODULE.element_to_lead(
            {
                "type": "node",
                "id": 1,
                "tags": {
                    "name": "Test Curl",
                    "shop": "hairdresser",
                    "contact:website": "https://n123.yclients.ru/",
                    "contact:instagram": "@testcurl",
                    "phone": "+7 900 000-00-00",
                },
            }
        )
        self.assertIsNotNone(lead)
        self.assertEqual(lead.website_url, "")
        self.assertIn("yclients.ru", lead.booking_url)
        self.assertEqual(lead.priority, "A")
        self.assertIn("онлайн-запись", lead.message)

    def test_standalone_site_lowers_score(self):
        lead = MODULE.element_to_lead(
            {
                "type": "node",
                "id": 2,
                "tags": {
                    "name": "Full Site",
                    "shop": "beauty",
                    "website": "https://example.com",
                    "phone": "+7 900 000-00-00",
                },
            }
        )
        self.assertLess(lead.score, 50)
        self.assertIn("уже есть отдельный сайт", lead.reasons)

    def test_fixture_exports_csv_and_html(self):
        payload = MODULE.load_payload(ROOT / "fixtures" / "overpass_sample.json", MODULE.MOSCOW_BBOX)
        leads = MODULE.leads_from_payload(payload, 50)
        self.assertEqual([lead.name for lead in leads], ["Curl Lab Moscow", "Brow Place", "Lash Room"])
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            MODULE.write_csv(leads, directory / "leads.csv")
            MODULE.write_html(leads, directory / "leads.html")
            with (directory / "leads.csv").open(encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 3)
            self.assertIn("Beauty Lead Finder", (directory / "leads.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
