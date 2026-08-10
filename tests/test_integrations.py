import asyncio
import json
import tempfile
import unittest
from pathlib import Path

import db
import seed
from web import integrations


class Upload:
    filename = "executive-sales-report.json"

    async def read(self, _limit):
        return json.dumps({
            "visuals": [
                {"measure": "revenue", "dimension": "month"},
                {"measure": "revenue", "dimension": "region"},
            ]
        }).encode()


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        db.DB_PATH = str(Path(self.tempdir.name) / "fastbi-test.sqlite")
        seed.build()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_private_schema_url_is_rejected(self):
        with self.assertRaises(integrations.IntegrationError):
            integrations._validate_public_url("http://127.0.0.1/schema.json")

    def test_openapi_schema_is_summarised(self):
        raw = json.dumps({
            "openapi": "3.1.0",
            "info": {"title": "Warehouse"},
            "components": {"schemas": {"Order": {"properties": {"revenue": {"type": "number"}}}}},
        }).encode()
        summary = integrations._schema_summary(raw, "application/json")
        self.assertIn("Warehouse", summary)
        self.assertIn("Order(revenue number)", summary)

    def test_report_upload_generates_editable_dashboard(self):
        dashboard_id = asyncio.run(integrations.generate_migration({
            "report": Upload(),
            "source_tool": "Power BI",
            "integration_id": "",
            "instructions": "Preserve revenue trends and regions",
        }))
        dashboard = db.one("SELECT * FROM dashboards WHERE id=?", (dashboard_id,))
        self.assertIn("Migrated Power BI", dashboard["title"])
        self.assertGreaterEqual(len(db.dashboard_charts(dashboard_id)), 1)
        self.assertEqual(db.migrations()[0]["dashboard_id"], dashboard_id)


if __name__ == "__main__":
    unittest.main()
