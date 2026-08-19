import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

import rag
from web import rag_views
from web.layout import page


class RAGTests(unittest.TestCase):
    def test_chunking_is_bounded_and_overlapping(self):
        text = "first sentence. " * 200
        with patch.dict(os.environ, {"FASTBI_RAG_CHUNK_SIZE":"200", "FASTBI_RAG_CHUNK_OVERLAP":"30"}):
            chunks = rag.chunk_text(text)
        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(len(chunk) <= 200 for chunk in chunks))

    def test_hash_embeddings_are_normalized_and_deterministic(self):
        with patch.dict(os.environ, {"FASTBI_RAG_EMBEDDING_PROVIDER":"hash", "FASTBI_RAG_EMBEDDING_DIMENSIONS":"64"}):
            first = rag.embed(["customer orders", "revenue"])
            second = rag.embed(["customer orders", "revenue"])
        np.testing.assert_array_equal(first, second)
        np.testing.assert_allclose(np.linalg.norm(first, axis=1), [1, 1])

    def test_graphrag_workspace_has_all_three_approaches(self):
        with patch("rag.health", return_value={"configured":True,"connected":True,"chunks":8,
              "embedding_model":"test","top_k":3}):
            html = "".join(str(x) for x in page("graphrag", "FastBI", "a@example.com", "thread", *rag_views.workspace()))
        self.assertIn("GraphRAG Chat", html)
        self.assertIn("PostgreSQL vector", html)
        self.assertIn("FAISS", html)
        self.assertIn("Compare all", html)

    def test_answer_rejects_unknown_approach(self):
        with self.assertRaises(rag.RAGError):
            rag.answer("question", "unknown")


if __name__ == "__main__":
    unittest.main()
