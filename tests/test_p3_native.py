"""Native graph expectations fixed independently of runtime SQL/response assembly."""
import pytest


def tag(name, ident=1, **fields):
    return dict(id=ident,name=name,category=4,post_count=1,is_deprecated=False,**fields)


def alias(a,b,ident=1,status='active'):
    return {'id':ident,'antecedent_name':a,'consequent_name':b,'status':status}


def test_native_terminal_and_directed_chain():
    from sakura_knowledge.native_tags import assess
    out = assess([tag('C')],[alias('A','B',1),alias('B','C',2)],{'A','B','C'})
    assert out['A'] == {'terminal':'C','canonical_status':'canonical','reason':None,'chain':[1,2],'category':4}
    assert out['C']['terminal'] == 'C' and out['C']['chain'] == []
    assert 'A' not in {x['name'] for x in [tag('C')]}  # spelling not fabricated native identity


@pytest.mark.parametrize('tags,aliases,scope,name,reason',[
    ([tag('A')],[],set(),'A','alias_scope_partial'),
    ([tag('C')],[alias('A','B'),alias('B','A',2)],{'A','B','C'},'A','alias_cycle'),
    ([tag('B'),tag('C',2)],[alias('A','B'),alias('A','C',2)],{'A','B','C'},'A','multiple_active_aliases'),
    ([],[alias('A','B')],{'A','B'},'A','missing_native_terminal'),
    ([{'id':1,'name':'A','category':4,'post_count':1,'is_deprecated':True}],[],{'A'},'A','deprecated_terminal'),
    ([{'id':1,'name':'A','category':4,'post_count':1}],[],{'A'},'A','lifecycle_unknown'),
    ([tag('B')],[alias('A','B',status='unknown')],{'A','B'},'A','alias_status_unknown'),
])
def test_independent_invalid_graph_reasons(tags,aliases,scope,name,reason):
    from sakura_knowledge.native_tags import assess
    got = assess(tags,aliases,scope)[name]
    assert got['terminal'] is None and got['canonical_status'] == 'unknown' and got['reason'] == reason


def test_retired_deleted_do_not_redirect_or_implicate():
    from sakura_knowledge.native_tags import assess
    out=assess([tag('A'),tag('B',2)],[alias('A','B',status='deleted'),alias('B','A',2,'retired')],{'A','B'})
    assert out['A']['terminal']=='A' and out['B']['terminal']=='B'


def test_chain_bound_and_duplicate_native_conflict():
    from sakura_knowledge.native_tags import assess
    aliases=[alias(str(i),str(i+1),i+1) for i in range(17)]
    assert assess([tag('17')],aliases,{str(i) for i in range(18)})['0']['reason']=='alias_chain_limit'
    assert assess([tag('A'),tag('A',2)],[],{'A'})['A']['reason']=='native_conflict'
