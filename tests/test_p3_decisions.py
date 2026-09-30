import pytest

from sakura_knowledge.tag_decisions import normalized_links, replay


def decision(**updates):
    src={'kind':'character','namespace':'bangumi.character','value':'123'}
    dst={'kind':'tag','namespace':'danbooru.tag','value':'native'}
    d={'decision_id':'d1','src':src,'dst':dst,'relation':'entity_tag','decision':'candidate',
       'method':'shared-name','rule_version':'fixture1','evidence_refs':[],
       'reviewer_kind':'execution_agent','reviewer_id':'test-agent','time':'2026-09-30T00:00:00Z','supersedes':None}
    return dict(d,**updates)


@pytest.mark.parametrize('method',['shared-name','context','confidence','human_verified'])
def test_no_candidate_name_model_promotion(method):
    with pytest.raises(ValueError):
        replay([decision(decision='verified',method=method)])


def test_replay_bound_link_and_revocation_compile_fresh():
    d=decision(decision='verified',method='explicit_cross_source_link')
    d['evidence_refs']=[{'role':'cross_source_id_link','src':d['src'],'dst':d['dst'],
                         'source_id':'source','evidence_id':'id1','raw_sha256':'b'*64}]
    assert normalized_links([d])[0]['verification_status']=='verified'
    revoked=decision(decision_id='d2',decision='revoked',supersedes='d1',method='withdrawn')
    assert normalized_links([d,revoked])==[]
    with pytest.raises(ValueError):
        replay([d,decision(decision_id='d2')])


def test_invalid_supersedes_or_same_name_wrong_namespace():
    with pytest.raises(ValueError):
        replay([decision(supersedes='absent')])
    with pytest.raises(ValueError):
        replay([decision(dst={'kind':'tag','namespace':'local.tag_aggregate','value':'native'})])
