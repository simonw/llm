import llm


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
