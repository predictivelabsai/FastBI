import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
import graph_db
import seed
from web import ai, graph_ai, graph_views


VALID = b"""
ontology:
  id: test-ontology
  name: Test ontology
  version: '1.0'
nodes:
  - id: customer
    type: OntologyClass
    label: Customer
  - id: order
    type: OntologyClass
    label: Order
edges:
  - from: customer
    to: order
    type: PLACES
"""


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        db.DB_PATH = str(Path(self.tempdir.name) / "fastbi-test.sqlite")
        seed.build()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_json_yaml_ontology_contract_is_canonical(self):
        yaml_payload = graph_db.parse_ontology(VALID, "ontology.yaml")
        json_payload = graph_db.parse_ontology(
            json.dumps(yaml_payload).encode(), "ontology.json"
        )
        self.assertEqual(yaml_payload, json_payload)
        self.assertEqual(len(yaml_payload["nodes"]), 2)
        self.assertEqual(yaml_payload["edges"][0]["type"], "PLACES")
        self.assertEqual(graph_db.ontology_hash(yaml_payload), graph_db.ontology_hash(json_payload))

    def test_ontology_rejects_unknown_edge_endpoint(self):
        bad = VALID.replace(b"to: order", b"to: missing")
        with self.assertRaisesRegex(graph_db.OntologyError, "unknown node"):
            graph_db.parse_ontology(bad, "ontology.yaml")

    def test_cypher_guard_bounds_reads_and_rejects_writes(self):
        safe = graph_db.validate_cypher("MATCH (n:OntologyNode) RETURN n")
        self.assertTrue(safe.endswith(f"LIMIT {graph_db.MAX_QUERY_ROWS}"))
        with self.assertRaises(graph_db.CypherError):
            graph_db.validate_cypher("MATCH (n) DETACH DELETE n RETURN n")
        with self.assertRaises(graph_db.CypherError):
            graph_db.validate_cypher("CALL db.labels() YIELD label RETURN label")
        with self.assertRaises(graph_db.CypherError):
            graph_db.validate_cypher("MATCH (n) RETURN n LIMIT 99999")
        with self.assertRaises(graph_db.CypherError):
            graph_db.validate_cypher("MATCH (n) RETURN n UNION MATCH (m) RETURN m")

    def test_automatic_router_keeps_manual_overrides(self):
        self.assertEqual(ai.route_mode("show revenue by month", "auto"), "sql")
        self.assertEqual(ai.route_mode("show revenue", "graph"), "graph")
        with patch("graph_db.configured", return_value=True):
            self.assertEqual(ai.route_mode("which classes are connected?", "auto"), "graph")

    def test_text_to_cypher_uses_structured_parameters(self):
        response = json.dumps({
            "cypher": "MATCH (n:OntologyClass) WHERE n.label=$label RETURN n LIMIT 20",
            "parameters": {"label": "Customer"},
            "explanation": "Find the Customer class.",
        })
        with patch("graph_db.schema_prompt", return_value="(:OntologyClass)"), \
             patch("web.ai._complete", return_value=response):
            cypher, params, note = graph_ai.text_to_cypher("find Customer")
        self.assertIn("$label", cypher)
        self.assertEqual(params, {"label": "Customer"})
        self.assertIn("Customer", note)

    def test_import_history_supports_activation_and_rollback_selection(self):
        payload = graph_db.parse_ontology(VALID, "ontology.yaml")
        meta = payload["ontology"]
        first = db.stage_graph_import(meta["id"], meta["name"], "1.0", "one.yaml",
                                      graph_db.ontology_hash(payload), graph_db.ontology_json(payload), "admin@example.com")
        db.activate_graph_import(first)
        payload["ontology"]["version"] = "2.0"
        second = db.stage_graph_import(meta["id"], meta["name"], "2.0", "two.yaml",
                                       graph_db.ontology_hash(payload), graph_db.ontology_json(payload), "admin@example.com")
        db.activate_graph_import(second)
        previous = db.previous_graph_import(meta["id"], second)
        self.assertEqual(previous["id"], first)
        self.assertEqual(db.graph_import(second)["status"], "active")

    def test_graph_visualisation_renders_vis_network(self):
        payload = {
            "nodes": [{"id": "1", "label": "Customer", "group": "OntologyClass", "properties": {}}],
            "edges": [], "stats": "1 node · 0 relationships",
        }
        html = "".join(str(item) for item in graph_views.graph_explorer(payload, [], ""))
        self.assertIn("vis-network@9.1.9", html)
        self.assertIn("ontology-network", html)
        self.assertIn("Graph Explorer", html)


if __name__ == "__main__":
    unittest.main()
