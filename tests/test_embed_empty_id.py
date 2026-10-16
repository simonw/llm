import unittest

from sqlite_utils import Database

import llm


class FixedEmbeddingModel(llm.EmbeddingModel):
    model_id = "empty-id-test"

    def embed_batch(self, items, *, key=None):
        vectors = {
            "query": [1.0, 0.0],
            "neighbor": [1.0, 1.0],
        }
        for item in items:
            yield vectors[item]


class TestSimilarEmptyId(unittest.TestCase):
    def make_collection(self, source_id):
        db = Database(memory=True, execute_plugins=False)
        collection = llm.Collection("test", db=db, model=FixedEmbeddingModel())
        self.addCleanup(collection.db.close)
        collection.embed(source_id, "query", store=True)
        collection.embed("neighbor", "neighbor", store=True)
        self.assertEqual(collection.count(), 2)
        self.assertEqual(
            collection.db["embeddings"].get((collection.id, source_id))["content"],
            "query",
        )
        return collection

    def test_similar_by_id_excludes_empty_id(self):
        collection = self.make_collection("")
        results = collection.similar_by_id("", number=1)
        self.assertEqual([entry.id for entry in results], ["neighbor"])

    def test_similar_by_vector_excludes_empty_id(self):
        collection = self.make_collection("")
        results = collection.similar_by_vector([1.0, 0.0], number=1, skip_id="")
        self.assertEqual([entry.id for entry in results], ["neighbor"])

    def test_similar_by_id_excludes_regular_ids(self):
        for source_id in ("source", "0"):
            with self.subTest(source_id=source_id):
                collection = self.make_collection(source_id)
                results = collection.similar_by_id(source_id, number=1)
                self.assertEqual([entry.id for entry in results], ["neighbor"])

    def test_similar_by_vector_none_keeps_empty_id(self):
        collection = self.make_collection("")
        results = collection.similar_by_vector([1.0, 0.0], number=1, skip_id=None)
        self.assertEqual([entry.id for entry in results], [""])
