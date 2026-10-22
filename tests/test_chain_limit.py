import pytest

import llm


def ping() -> str:
    "Ping"
    return 'pong'


class LoopingModel(llm.Model):
    """A model that asks for a tool on every turn, so only the chain limit stops it."""

    model_id = 'looping'
    supports_tools = True

    def execute(self, prompt, stream, response, conversation):
        response.add_tool_call(llm.ToolCall(name='ping', arguments={}))
        yield 'calling ping'


def responses_before_stopping(chain):
    """Number of responses consumed before the chain limit raises."""
    count = 0
    with pytest.raises(ValueError, match='Chain limit'):
        for response in chain.responses():
            response.text()
            count += 1
    return count


def test_conversation_chain_limit_defaults_to_ten():
    # Conversation.chain() falls back to self.chain_limit, so this default is the one the Python API uses.
    assert llm.Conversation(model=LoopingModel()).chain_limit == 10


def test_model_chain_is_bounded_by_default():
    assert responses_before_stopping(LoopingModel().chain('go', tools=[ping])) == 10


def test_conversation_chain_is_bounded_by_default():
    chain = LoopingModel().conversation().chain('go', tools=[ping])
    assert responses_before_stopping(chain) == 10


def test_explicit_chain_limit_still_wins():
    chain = LoopingModel().conversation(chain_limit=3).chain('go', tools=[ping])
    assert responses_before_stopping(chain) == 3
def test_chain_limit_zero_opts_out():
    # chain_limit=0 is falsy, so the loop is not bounded - documented as the opt-out.
    chain = LoopingModel().conversation(chain_limit=0).chain('go', tools=[ping])
    assert chain.chain_limit == 0
    count = 0
    for response in chain.responses():
        response.text()
        count += 1
        if count >= 15:
            break
    assert count == 15
