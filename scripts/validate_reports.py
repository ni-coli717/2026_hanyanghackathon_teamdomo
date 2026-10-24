"""주민 제보 정리본 검증 + events.csv 생성

사용: python validate_reports.py [data_dir]
  data_dir 기본값: gimpo/data/private
  읽는 파일: reports_raw.csv, reports.csv, 장소_대응표.csv
  만드는 파일: events.csv
"""
import csv, sys, os, re, statistics, datetime as dt
from collections import Counter, defaultdict

PERIOD_START = dt.date(2026, 6, 20)
PERIOD_END = dt.date(2026, 9, 30)
EVENT_GAP_MIN = 60

ALLOWED = {
    'source': {'kakao', 'dm', 'memo', 'excel', 'verbal'},
    'participant_id': {'P00', 'P01', 'P02', 'P03', 'P04', 'P05'},
    'time_precision': {'exact', 'hour', 'part', 'unknown'},
    'zone_id': {'U01', 'U02', 'U03', 'G01', 'OUT'},
    'location_kind': {'outdoor', 'indoor_open', 'indoor_closed', 'unknown'},
    'odor_detected': {'true', 'false'},
    'intensity': {'', '1', '2', '3'},
    'odor_type': {'unknown'},
    'quality': {'A', 'B', 'C'},
    'record_origin': {'resident_spontaneous_archive'},
    'time_basis': {'stated_exact', 'stated_now', 'stated_hour', 'part_default', 'date_only', 'sent_at_proxy', 'sent_at_proxy_vague', 'insta_separator_proxy'},
    'place_basis': {'stated', 'assumed_home'},
    'source_check': {'kakao_export', 'capture_not_attached', 'capture_attached'},
}
# 원문에 근거가 있어야 하는 값
OUTDOOR_CUE = ['밖에서', '가는길', '버스 기다리는데', '산책', '밥먹으러 왔는데']
INDOOR_OPEN_CUE = ['창문 열', '창문열', '열어놨']
INDOOR_CLOSED_CUE = ['닫았는데', '닫아도', '문닫아도', '학원 안인데']

def support_errors(r, t):
    e = []
    if r['duration_min'] and not re.search(r'\d+분째|시간째', t): e.append(f'duration_min={r["duration_min"]} 원문 근거 없음')
    if r['weather_text'] and r['weather_text'] not in t: e.append('weather_text 원문에 없음')
    if r['intensity_text'] and r['intensity_text'] not in t: e.append('intensity_text 원문에 없음')
    if r['odor_type_text'] and not all(p.strip() in t for p in r['odor_type_text'].split(',')): e.append('odor_type_text 원문에 없음')
    if r['intensity'] and r['intensity'] not in t: e.append('intensity 숫자가 원문에 없음')
    cue = {'outdoor': OUTDOOR_CUE, 'indoor_open': INDOOR_OPEN_CUE, 'indoor_closed': INDOOR_CLOSED_CUE}.get(r['location_kind'])
    if cue and not any(c in t for c in cue): e.append(f'location_kind={r["location_kind"]} 원문 근거 없음')
    return e

def kakao_messages(src_dir):
    import glob
    msgs = defaultdict(list)
    files = glob.glob(os.path.join(src_dir, 'KakaoTalk_*.txt'))
    if not files: return None, None
    cur = None; last = None
    for line in open(files[0], encoding='utf-8'):
        line = line.rstrip('\n')
        m = re.match(r'-+ \w+, (\d+) (\w+) (\d{4}) -+$', line)
        if m:
            cur = dt.datetime.strptime(f'{m.group(1)} {m.group(2)} {m.group(3)}', '%d %B %Y').date(); continue
        m = re.match(r'\[(.+?)\] \[(\d+):(\d+) ([AP]M)\] (.*)$', line)
        if m and cur:
            h = int(m.group(2)) % 12 + (12 if m.group(4) == 'PM' else 0)
            t = dt.datetime.combine(cur, dt.time(h, int(m.group(3))))
            last = [m.group(1), m.group(5)]; msgs[t].append(last)
        elif last is not None and line:
            last[1] += '\n' + line
    return msgs, os.path.basename(files[0])
PREC_RANK = {'exact': 0, 'hour': 1, 'part': 2, 'unknown': 3}

def read(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def quality(prec, zone, source):
    q = 'A' if prec in ('exact', 'hour') and zone != 'OUT' else 'B' if prec == 'part' and zone else 'C'
    if source == 'verbal':
        q = {'A': 'B', 'B': 'C', 'C': 'C'}[q]
    return q

def main(d):
    raw = read(os.path.join(d, 'reports_raw.csv'))
    rep = read(os.path.join(d, 'reports.csv'))
    places = {r['place_text']: r['zone_id'] for r in read(os.path.join(d, '장소_대응표.csv'))}
    errs, warns = [], []

    ids = [r['raw_id'] for r in raw]
    if len(ids) != len(set(ids)): errs.append('raw_id 중복')
    rawmap = {r['raw_id']: r for r in raw}
    for r in raw:
        if not r['source'] or not r['source_ref']: errs.append(f"{r['raw_id']}: source/source_ref 비어 있음")
        if r['source'] not in ALLOWED['source']: errs.append(f"{r['raw_id']}: source 허용값 밖 {r['source']}")
        if r['participant_id'] not in ALLOWED['participant_id']: errs.append(f"{r['raw_id']}: participant_id 허용값 밖")
        if re.search(r'01[016789]-?\d{3,4}-?\d{4}', r['raw_text']): errs.append(f"{r['raw_id']}: 전화번호로 보이는 문자열")

    rids = [r['report_id'] for r in rep]
    if len(rids) != len(set(rids)): errs.append('report_id 중복')
    for r in rep:
        rid = r['report_id']
        if rid not in rawmap: errs.append(f'{rid}: raw에 없는 report_id'); continue
        for col in ('report_id', 'participant_id', 'observed_date', 'time_precision'):
            if not r[col]: errs.append(f'{rid}: {col} 비어 있음')
        for col, allowed in ALLOWED.items():
            if col in r and r[col] not in allowed: errs.append(f'{rid}: {col} 허용값 밖 "{r[col]}"')
        try:
            od = dt.date.fromisoformat(r['observed_date'])
            if not (PERIOD_START <= od <= PERIOD_END): errs.append(f'{rid}: 기간 밖 날짜 {od}')
        except ValueError:
            errs.append(f'{rid}: 날짜 형식 오류'); continue
        if not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', r['observed_time']): errs.append(f'{rid}: 시각 형식 오류')
        if r['intensity'] == '0': errs.append(f'{rid}: intensity 0')
        if r['place_text'] not in places: errs.append(f'{rid}: 장소 대응표에 없는 place_text "{r["place_text"]}"')
        elif places[r['place_text']] != r['zone_id']: errs.append(f'{rid}: zone_id가 대응표와 다름')
        q = quality(r['time_precision'], r['zone_id'], rawmap[rid]['source'])
        if r['quality'] != q: errs.append(f'{rid}: quality {r["quality"]} ≠ 계산값 {q}')
        if r['participant_id'] != rawmap[rid]['participant_id']: warns.append(f'{rid}: participant_id가 raw와 다름')
        for e_ in support_errors(r, rawmap[rid]['raw_text']): errs.append(f'{rid}: {e_}')
        for col in ('window_start', 'window_end'):
            if r.get(col) and not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}', r[col]): errs.append(f'{rid}: {col} 형식 오류')

    # 카톡 원본 대조: raw의 kakao 줄이 내보내기 파일의 같은 시각 메시지와 같은지
    src = os.path.join(d, 'reports_source')
    km, kfile = kakao_messages(src)
    k_ok = k_bad = 0
    if km is not None:
        for r in raw:
            if r['source'] != 'kakao': continue
            t = dt.datetime.fromisoformat(r['sent_at'])
            pool = [m_[1] for dd in (0, 1) for m_ in km.get(t + dt.timedelta(minutes=dd), [])]
            pieces = r['raw_text'].split(' / ')
            def found(p):
                pat = re.escape(p).replace(re.escape('[이름]'), r'\S+')
                return any(re.fullmatch(pat, q) for q in pool)
            if all(found(p) for p in pieces): k_ok += 1
            else: k_bad += 1; errs.append(f"{r['raw_id']}: 카톡 내보내기 파일의 {r['sent_at']} 메시지와 본문 불일치")
    # 인스타 캡처 이미지 존재
    caps = Counter()
    for r in raw:
        if r['source'] == 'dm':
            m = re.search(r'(IMG_\d+\.PNG)', r['source_ref'])
            caps['있음' if m and os.path.exists(os.path.join(src, m.group(1))) else '없음'] += 1
    if caps['없음']: warns.append(f"인스타 캡처 이미지 {caps['없음']}건이 reports_source에 없음 → 원문 대조 불가(source_check=capture_not_attached)")
    # 같은 사람·같은 날, 날짜만 있는 회고와 다른 제보가 같이 있으면 같은 사건일 수 있음
    for r in rep:
        if r.get('time_basis') == 'date_only':
            same = [q['report_id'] for q in rep if q is not r and q['participant_id'] == r['participant_id'] and q['observed_date'] == r['observed_date']]
            if same: warns.append(f"{r['report_id']}: 날짜만 있는 회고, 같은 날 같은 사람 제보 {';'.join(same)}와 같은 사건일 수 있음")

    # 30분 안 같은 사람·같은 구역 → 병합 누락 경고
    def ts(r): return dt.datetime.fromisoformat(f"{r['observed_date']} {r['observed_time']}")
    by = defaultdict(list)
    for r in rep:
        if r['odor_detected'] == 'true' and r['participant_id'] != 'P00' and r['time_precision'] != 'unknown':
            by[(r['participant_id'], r['zone_id'])].append(r)
    for k, lst in by.items():
        lst.sort(key=ts)
        for a, b in zip(lst, lst[1:]):
            if (ts(b) - ts(a)).total_seconds() < 1800: warns.append(f"{a['report_id']}·{b['report_id']}: 같은 사람 30분 안 제보(병합 검토)")

    # ---------- events ----------
    det = sorted([r for r in rep if r['odor_detected'] == 'true'], key=lambda r: (r['zone_id'], ts(r)))
    events, cur = [], None
    def close(ev):
        if ev: events.append(ev)
    for r in det:
        t = ts(r); dur = int(r['duration_min']) if r['duration_min'] else 0
        if r['time_precision'] == 'unknown':
            close(cur); cur = None
            events.append(dict(zone=r['zone_id'], start=t, end=t, rows=[r])); continue
        if cur and cur['zone'] == r['zone_id'] and (t - cur['last']).total_seconds() <= EVENT_GAP_MIN * 60:
            cur['rows'].append(r); cur['last'] = t; cur['end'] = max(cur['end'], t + dt.timedelta(minutes=dur))
        else:
            close(cur); cur = dict(zone=r['zone_id'], start=t, end=t + dt.timedelta(minutes=dur), last=t, rows=[r])
    close(cur)
    events.sort(key=lambda e: e['start'])
    out = []
    for i, e in enumerate(events, 1):
        rows = e['rows']
        ints = [int(r['intensity']) for r in rows if r['intensity']]
        types = Counter(r['odor_type'] for r in rows).most_common()
        maj = types[0][0] if len(types) == 1 or types[0][1] > types[1][1] else 'mixed'
        out.append(dict(event_id=f'E{i:04d}', zone_id=e['zone'], start_at=e['start'].strftime('%Y-%m-%d %H:%M'), end_at=e['end'].strftime('%Y-%m-%d %H:%M'),
                        n_reports=len(rows), n_participants=len({r['participant_id'] for r in rows if r['participant_id'] != 'P00'}),
                        intensity_max=max(ints) if ints else '', intensity_median=statistics.median(ints) if ints else '',
                        odor_type_majority=maj, time_precision_worst=max((r['time_precision'] for r in rows), key=PREC_RANK.get),
                        quality=min(r['quality'] for r in rows),
                        n_place_assumed=sum(r.get('place_basis') == 'assumed_home' for r in rows),
                        n_time_estimated=sum(r.get('time_basis') in ('part_default', 'date_only', 'insta_separator_proxy', 'sent_at_proxy_vague') for r in rows),
                        report_ids=';'.join(r['report_id'] for r in rows)))
    with open(os.path.join(d, 'events.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)

    # ---------- 출력 ----------
    print(f'대상 기간 {PERIOD_START} ~ {PERIOD_END}')
    print(f'raw {len(raw)}줄 → reports {len(rep)}줄 (제외 {len(raw) - len(rep)}줄: 날짜 없음·기간 밖·중복 병합)')
    if km is not None: print(f'카톡 원본 대조: {k_ok}줄 일치, {k_bad}줄 불일치 ({kfile})')
    print(f'인스타 캡처: 이미지 있음 {caps["있음"]}건, 없음 {caps["없음"]}건')
    print(f'오류 {len(errs)}건, 경고 {len(warns)}건')
    for e in errs[:30]: print('  [오류]', e)
    for w_ in warns[:30]: print('  [경고]', w_)
    def show(title, c):
        print(f'\n[{title}]'); [print(f'  {k}: {v}') for k, v in sorted(c.items())]
    show('참여자별', Counter(r['participant_id'] for r in rep))
    show('월별', Counter(r['observed_date'][:7] for r in rep))
    def band(r):
        if r['time_precision'] == 'unknown': return '9 시각 모름'
        h = int(r['observed_time'][:2])
        return '1 새벽(02-06)' if 2 <= h < 6 else '2 아침(06-09)' if h < 9 and h >= 6 else '3 낮(09-17)' if 9 <= h < 17 else '4 저녁(17-21)' if 17 <= h < 21 else '5 밤(21-02)'
    show('시간대별', Counter(band(r) for r in rep))
    show('품질별', Counter(r['quality'] for r in rep))
    show('구역별', Counter(r['zone_id'] for r in rep))
    show('정밀도별', Counter(r['time_precision'] for r in rep))
    show('시각 근거별(time_basis)', Counter(r.get('time_basis', '') for r in rep))
    show('장소 근거별(place_basis)', Counter(r.get('place_basis', '') for r in rep))
    print('\n※ 이 검사는 형식·허용값·원문 대조·규칙 재계산을 확인할 뿐, 제보가 실제 관측인지 인증하지 않음')
    print(f"\n냄새 없음(false) {sum(r['odor_detected'] == 'false' for r in rep)}건은 사건 묶기에서 제외")
    print(f'사건 {len(out)}건, 집단 사건(2명 이상) {sum(e["n_participants"] >= 2 for e in out)}건')
    show('사건 구역별', Counter(e['zone_id'] for e in out))
    return 1 if errs else 0

if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.path.join('gimpo', 'data', 'private')))
