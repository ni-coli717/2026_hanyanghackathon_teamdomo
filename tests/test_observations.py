from datetime import datetime, timezone
from uuid import uuid4
import pandas as pd
from core.config import classify_collection_mode
from core.observations import LocalObservations, build_observation, legacy_reports, kst
from core.features import make_windows


def observation(odor,participant='R01',context='outdoor',moment=None):
    return build_observation(participant,'Z2',context,odor,2,'기타',str(uuid4()),moment or datetime(2026,9,18,7,30))


def test_kst_and_schedule_boundaries():
    assert kst('2026-09-17T22:30:00Z').hour==7
    assert classify_collection_mode(datetime(2026,9,17,22,30,tzinfo=timezone.utc))[0]=='scheduled'
    assert classify_collection_mode(datetime(2026,9,18,7,15))[0]=='scheduled'
    assert classify_collection_mode(datetime(2026,9,18,7,45))[0]=='scheduled'
    assert classify_collection_mode(datetime(2026,9,18,7,45,1))[0]=='spontaneous'
    assert pd.Timestamp(observation(False,moment=datetime(2026,9,18,7,15))['window_id']).minute==30
    assert pd.Timestamp(observation(False,moment=datetime(2026,9,18,7,45))['window_id']).hour==7


def test_idempotency_and_tristate(tmp_path):
    repo=LocalObservations(tmp_path/'new.db')
    for value in (True,False,None):
        row=observation(value)
        assert repo.save_observation(row)
        assert not repo.save_observation(row)
    assert len(repo.get_recent_observations())==3
    assert {str(r['odor_detected']) for r in repo.get_recent_observations()}=={'True','False','None'}
    assert not repo.get_observations_by_participant('R99')


def test_denominator_excludes_unknown_indoor_extra_and_followup():
    rows=[observation(True,'R01'),observation(False,'R02'),observation(False,'R03'),observation(None,'R04'),observation(True,'R05','indoor')]
    rows.append(observation(True,'R06',moment=datetime(2026,9,18,9,0)))
    follow=observation(True,'R07'); follow['collection_mode']='followup'; rows.append(follow)
    w=make_windows(legacy_reports(rows),pd.DataFrame(columns=['weather_at']),pd.read_csv('data/sample/zones.csv'),pd.read_csv('data/sample/sources.csv'))
    assert len(w)==1 and w.iloc[0].n_observers==3 and w.iloc[0].n_detected==1


def test_latest_unknown_supersedes_previous_answer():
    rows=[observation(True,'R01'),observation(None,'R01'),observation(False,'R02'),observation(False,'R03')]
    rows[1]['received_at']='2026-09-18T09:00:00+09:00'
    rows[0]['received_at']='2026-09-18T08:00:00+09:00'
    w=make_windows(legacy_reports(rows),pd.DataFrame(columns=['weather_at']),pd.read_csv('data/sample/zones.csv'),pd.read_csv('data/sample/sources.csv'))
    assert w.iloc[0].n_observers==2 and pd.isna(w.iloc[0].label)
