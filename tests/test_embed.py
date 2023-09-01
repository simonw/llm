import llm
import sqlite_utils


def test_demo_plugin():
    model = llm.get_embedding_model("embed-demo")
    assert model.embed("hello world") == [5, 5] + [0] * 14


def test_embed_huge_list():
    model = llm.get_embedding_model("embed-demo")
    huge_list = ("hello {}".format(i) for i in range(1000))
    results = model.embed_multi(huge_list)
    assert repr(type(results)) == "<class 'generator'>"
    first_twos = {}
    for result in results:
        key = (result[0], result[1])
        first_twos[key] = first_twos.get(key, 0) + 1
    assert first_twos == {(5, 1): 10, (5, 2): 90, (5, 3): 900}
    # Should have happened in 100 batches
    assert model.batch_count == 100


def test_collection():
    db = sqlite_utils.Database(memory=True)
    collection = llm.Collection(db, "test", model_id="embed-demo")
    assert collection.id() == 1
    assert collection.count() == 0
    # Embed some stuff
    collection.embed(1, "hello world")
    collection.embed(2, "goodbye world")
    assert collection.count() == 2
    # Check that the embeddings are there
    rows = list(db["embeddings"].rows)
    assert rows == [
        {
            "collection_id": 1,
            "id": "1",
            "embedding": llm.encode([5, 5, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
            "content": None,
            "metadata": None,
        },
        {
            "collection_id": 1,
            "id": "2",
            "embedding": llm.encode([7, 5, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
            "content": None,
            "metadata": None,
        },
    ]
