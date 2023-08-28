import llm


def test_demo_plugin():
    model = llm.get_embedding_model("embed-demo")
    assert model.embed("hello world") == [5, 5] + [0] * 14
