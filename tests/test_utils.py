import pytest
from llm.utils import remove_pref

inps = [('My fave color',['is', ' orange']),
    ('My fave color',['My', ' fave', ' is', ' orange']),
    ('My fave color',['My', ' fave', ' color', ' is', ' orange']),
    ('My fave color',['fave', ' color', ' is', ' orange']),
    ('My fave color',['My fave color is', ' orange']),
    ('My fave color',['My fave color', ' is orange'])]

exps = ['My fave color is orange',
    'My fave color My fave is orange',
    'My fave color is orange',
    'My fave color fave color is orange',
    'My fave color is orange',
    'My fave color is orange']

@pytest.mark.parametrize("p_r,exp", zip(inps, exps))
def test_remove_pref(p_r, exp):
    assert ''.join(remove_pref(*p_r)) == exp

