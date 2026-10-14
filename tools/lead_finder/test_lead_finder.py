import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("lead_finder", ROOT / "lead_finder.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class LeadFinderTests(unittest.TestCase):
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
