import json
import pandas as pd
from core.map_data import prepare_payload, resolve_selection, in_service
from core.public_data import dashboard


def test_public_payload_and_time_alignment():
    r,w,z,_,v,_=dashboard('demo')
    p=prepare_payload(r,w,z,v,True)
    assert len(p['frames'])>=32
    assert len({f['at'] for f in p['frames']})==len(p['frames'])
    text=json.dumps(p)
    assert 'observer_code' not in text and 'R01' not in text
    for f in p['frames']:
        if f['wind']:
            assert f['wind']['to']==(f['wind']['from']+180)%360
            assert 0 <= (pd.Timestamp(f['at'])-pd.Timestamp(f['wind']['at'])).total_seconds() <= 3600
    assert resolve_selection(p,{})['zone_id']=='Z2'
    assert resolve_selection(p,{'position':[37.7,126.6]})['zone_id'] is None
    assert not in_service(37.5,127.1)
    assert resolve_selection(p,{'position':[37.5,127.1]})['position']==[37.654,126.680]


def test_no_weather_unknown_and_absent_not_safe():
    r,w,z,_,v,_=dashboard('demo')
    r=r.iloc[:3].copy()
    r['zone_id']='Z2';r['odor']=None
    p=prepare_payload(r,w.iloc[:0],z,pd.DataFrame(),False)
    assert p['frames'][0]['wind'] is None
    assert p['frames'][0]['zones']['Z2']['status']=='자료 부족'
    assert p['frames'][0]['zones']['Z1']['status']=='자료 없음'
    assert not p['frames'][0]['zones']['Z2']['odor_evidence']


def test_ne_wind_and_type_require_observation_evidence():
    r,w,z,_,v,_=dashboard('demo')
    r=r.iloc[:3].copy();r['zone_id']='Z2';r['odor']=1;r['odor_type']='하수구와 비슷함'
    w=w.iloc[:1].copy();w['weather_at']=pd.Timestamp(r.observed_at.iloc[0]).round('30min');w['wd']=45.;w['ws']=2.
    p=prepare_payload(r,w,z,pd.DataFrame(),True)
    f=p['frames'][0]
    assert f['wind']['from']==45 and f['wind']['to']==225
    assert f['zones']['Z2']['type']=='sewage'
    r['odor']=0
    p=prepare_payload(r,w,z,pd.DataFrame(),True)
    assert not p['frames'][0]['zones']['Z2']['odor_evidence']
