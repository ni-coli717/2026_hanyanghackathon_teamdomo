'use strict';
// Native Streamlit component protocol. Estimates arrive from Python (analysis_service); nothing is invented here.
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let data, state, map, tiles, flows, markers, pin, selection, timer=null, picking=false, rendered=false, tileFailures=0, locationRequest=0, needleAngle=null;
const emptyStat={n:0,detected:0,status:'자료 없음',type:'unknown',odor_evidence:false,median:null,pred:null,arrow:'none'};
const LEVEL_CLASS={'높음':'high','보통':'medium','낮음':'low'};
const post=(type,extra={})=>window.parent.postMessage({isStreamlitMessage:true,type,...extra},'*');
function send(){
 if(!map||!state)return;
 state.center=[map.getCenter().lat,map.getCenter().lng];state.zoom=map.getZoom();
 state.sequence=(state.sequence||0)+1;
 post('streamlit:setComponentValue',{value:{...state},dataType:'json'});
}
function parts(iso){return Object.fromEntries(new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(iso)).map(x=>[x.type,x.value]));}
function fmt(iso){if(!iso)return '자료 없음';const p=parts(iso);return `${p.month}.${p.day} ${p.hour}:${p.minute}`;}
// '14:30 기준' today, '09.16 22:00 기준' otherwise.
function basisTime(iso){if(!iso)return '자료 없음';const p=parts(iso),n=parts(new Date().toISOString());return (p.year===n.year&&p.month===n.month&&p.day===n.day?`${p.hour}:${p.minute}`:fmt(iso))+' 기준';}
function direction(deg){return ['북','북북동','북동','동북동','동','동남동','남동','남남동','남','남남서','남서','서남서','서','서북서','북서','북북서'][Math.round(((deg%360)+360)%360/22.5)%16];}
function deltaAngle(a,b){return ((b-a+540)%360)-180;}
function km(a,b){const r=Math.PI/180, dLat=(b[0]-a[0])*r,dLon=(b[1]-a[1])*r;const v=Math.sin(dLat/2)**2+Math.cos(a[0]*r)*Math.cos(b[0]*r)*Math.sin(dLon/2)**2;return 6371.0088*2*Math.atan2(Math.sqrt(v),Math.sqrt(1-v));}
function inRing(lat,lon,ring){let inside=false;for(let i=0,j=ring.length-1;i<ring.length;j=i++){const [x,y]=ring[i],[xx,yy]=ring[j];if((y>lat)!=(yy>lat)&&lon<(xx-x)*(lat-y)/(yy-y)+x)inside=!inside;}return inside;}
function inside(position){return data.boundary.features.some(f=>{const polys=f.geometry.type==='MultiPolygon'?f.geometry.coordinates:[f.geometry.coordinates];return polys.some(r=>inRing(...position,r[0])&&!r.slice(1).some(h=>inRing(...position,h)));});}
function nearby(){let closest=null,best=Infinity;data.zones.forEach(z=>{const dist=km(state.position,[z.lat,z.lon]);if(dist<best){closest=z;best=dist;}});return best<=2?closest:null;}
function frame(){return data.frames.find(f=>f.at===state.at)||null;}
function frameIndex(){return data.frames.findIndex(f=>f.at===state.at);}
function isForecast(f=frame()){return f?.kind==='forecast';}
function stat(){const z=nearby();return z?frame()?.zones[z.id]||emptyStat:emptyStat;}
function badgeClass(status){return /부족|없음/.test(status)?'hold':status==='집단 감지'?'high':status==='일부 감지'?'medium':'low';}
function message(text){$('notice').textContent=text;$('notice').hidden=false;}
function hideMessage(){$('notice').hidden=true;}
function choose(position,kind='selected'){
 locationRequest++;
 if(!inside(position)){message('김포 밖입니다 · 운양동에서 위치 선택');return false;}
 state.position=position;state.position_kind=kind;picking=false;$('pick').classList.remove('active');hideMessage();render();send();return true;
}
// Arrow kind for the selected spot: the zone's shared rule, or a neutral wind reference outside zones.
function spotKind(){
 const z=nearby(),w=frame()?.wind;
 if(z)return stat().arrow||'none';
 if(!w)return 'none';
 return w.speed<(data.calm_ms??.5)?'calm':'wind';
}
function hiddenByFilter(kind,pred){return kind==='odor'&&state.filter!=='all'&&pred?.type!==state.filter;}
function addDistance(latlon,bearing,distance){const a=bearing*Math.PI/180,p=latlon[0]*Math.PI/180,l=latlon[1]*Math.PI/180,d=distance/6371.0088;const q=Math.asin(Math.sin(p)*Math.cos(d)+Math.cos(p)*Math.sin(d)*Math.cos(a));return [q*180/Math.PI,(l+Math.atan2(Math.sin(a)*Math.sin(d)*Math.cos(p),Math.cos(d)-Math.sin(p)*Math.sin(q)))*180/Math.PI];}
function across(a,b,to){const r=Math.PI/180,dx=(b[1]-a[1])*Math.cos(a[0]*r)*111.32,dy=(b[0]-a[0])*110.57;return dx*Math.cos(to*r)-dy*Math.sin(to*r);}
function flowStyle(kind,pred,forecast){
 const color=kind==='odor'?data.types[pred.type][1]:'#64748B';
 const level=kind==='odor'?pred.level:null;
 return {color,weight:{'낮음':3,'보통':4,'높음':5}[level]||3,opacity:{'낮음':.7,'보통':.85,'높음':.95}[level]||.75,
  dashArray:forecast?'1 9':kind==='wind'?'4 8':({livestock:null,sewage:'12 7',other:'3 6',unknown:'7 7'}[pred.type]),lineCap:'round'};
}
// Lines anchored on zone representative points along the move_to bearing; a single-station wind is repeated, not modelled as dispersion.
function flowLines(){
 const f=frame(),w=f?.wind,sel=nearby();if(!w)return [];
 const lines=[];
 const push=(anchor,kind,pred,zone)=>{if(lines.every(l=>Math.abs(across(l.anchor,anchor,w.to))>=.3))lines.push({anchor,kind,pred,zone});};
 if(!sel){if(spotKind()==='wind')for(const o of [0,-.45,.45])push(addDistance(state.position,w.to+90,o),'wind',null,null);return lines;}
 // One line per zone (selected first); companions around the selected zone only until there are three.
 const order=[sel,...data.zones.filter(z=>z.id!==sel.id)].map(z=>({z,s:f.zones[z.id]||emptyStat}))
  .filter(({s})=>['odor','wind'].includes(s.arrow)&&!hiddenByFilter(s.arrow,s.pred));
 order.forEach(({z,s})=>push(addDistance([z.lat,z.lon],w.to+90,0),s.arrow,s.pred,z.id));
 const first=order.find(({z})=>z.id===sel.id);
 if(first)for(const o of [-.45,.45])if(lines.length<3)push(addDistance([sel.lat,sel.lon],w.to+90,o),first.s.arrow,first.s.pred,sel.id);
 return lines.slice(0,4);
}
function drawFlows(){
 flows.clearLayers();const f=frame(),w=f?.wind;if(!w)return;
 const forecast=isForecast(f);
 for(const line of flowLines()){
  const style=flowStyle(line.kind,line.pred,forecast);
  const start=addDistance(line.anchor,w.from,.8),end=addDistance(line.anchor,w.to,.8);
  L.polyline([start,end],{color:'white',weight:style.weight+4,opacity:.9,interactive:false,lineCap:'round'}).addTo(flows);
  L.polyline([start,end],{...style,bubblingMouseEvents:false}).on('click',()=>openPanel('flow')).addTo(flows);
  for(const dist of [-.6,-.2,.2,.6]){
   const point=addDistance(line.anchor,w.to,dist),size=12+style.weight;
   const icon=L.divIcon({className:'flow-head'+(forecast?' forecast':''),iconSize:[size,size],iconAnchor:[size/2,size/2],html:`<svg width="${size}" height="${size}" viewBox="0 0 20 20" aria-hidden="true" style="transform:rotate(${w.to}deg)"><path d="M4 15L10 5L16 15" fill="none" stroke="white" stroke-width="7" stroke-linejoin="round"/><path d="M4 15L10 5L16 15" fill="none" stroke="${style.color}" stroke-width="3.5" stroke-linejoin="round" ${forecast?'stroke-dasharray="3 2"':''}/></svg>`});
   L.marker(point,{icon,keyboard:true,title:line.kind==='odor'?'유입 추정 상세':'바람 이동 상세',bubblingMouseEvents:false}).on('click',()=>openPanel('flow')).addTo(flows);
  }
 }
}
function drawZones(){
 markers.clearLayers();const f=frame(),forecast=isForecast(f);
 data.zones.forEach(z=>{
  const s=f?.zones[z.id]||emptyStat;const color=forecast?'#9AA5AE':{hold:'#9AA5AE',high:'#C0563B',medium:'#D99A3C',low:'#3D8B5F'}[badgeClass(s.status)];
  const marker=L.circleMarker([z.lat,z.lon],{radius:9,color:'white',weight:3,fillColor:color,fillOpacity:.95,bubblingMouseEvents:false}).addTo(markers);
  const rep=window.appArgs.recent?.[z.id];
  const label=[z.name,forecast?'예보':s.status,s.arrow==='calm'?'방향 보류':'',rep?`제보 ${rep.count}`:''].filter(Boolean).map(esc).join(' · ');
  marker.bindTooltip(label,{direction:'top',offset:[0,-8],permanent:map.getZoom()>=12.5,className:s.arrow==='calm'?'zone-label calm':'zone-label'});
  marker.on('click',()=>{choose([z.lat,z.lon]);openPanel('zone');});
  const el=marker.getElement();if(el){el.setAttribute('tabindex','0');el.setAttribute('role','button');el.setAttribute('aria-label',z.name+' 상세');el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose([z.lat,z.lon]);openPanel('zone');}};}
 });
 pin.setLatLng(state.position).unbindTooltip().bindTooltip(state.position_kind==='gps'?'내 위치':'기준 위치',{permanent:true,direction:'right',offset:[12,0],className:'pin-label'});
}
// Rotate the needle along the shortest arc (359° -> 1° turns 2°, not 358°).
function setNeedle(deg){
 needleAngle=needleAngle===null?deg:needleAngle+deltaAngle(((needleAngle%360)+360)%360,deg);
 $('needle').style.transform=`rotate(${needleAngle}deg)`;
}
function levelLabel(pred){return pred?.level?`유입 가능성 ${pred.level}`:null;}
function render(){
 const z=nearby(),s=stat(),f=frame(),w=f?.wind,kind=spotKind(),pred=s.pred,index=frameIndex(),forecast=isForecast(f);
 $('demo').hidden=!data.demo;
 $('location-name').textContent=z?.name||'관측 구역 밖';
 $('summary').innerHTML=forecast
  ?`<span class="badge forecast">예보</span>${pred?.level?`<span>${esc(levelLabel(pred))}</span>`:''}`
  :`<span class="badge ${badgeClass(s.status)}">${esc(s.status)}</span>`+(s.n?`<span aria-label="${s.n}명 중 ${s.detected}명 감지">감지 ${s.detected}/${s.n}명</span>`:'');
 const rep=z&&window.appArgs.recent?.[z.id];if(rep)$('summary').innerHTML+=`<span class="badge report" aria-label="최근 3시간 제보 ${rep.count}건">제보 ${rep.count}</span>`;
 // Compass: level badge from the model, observation stays in the summary card.
 $('compass-title').textContent=state.position_kind==='gps'?'내 위치':z?.name||'선택 위치';
 const status=!f||kind==='none'?'자료 없음':pred?.level?levelLabel(pred):z&&pred?'추정 보류':'자료 없음';
 $('compass-status').textContent=status;$('compass-status').className='badge '+(LEVEL_CLASS[pred?.level]||'hold');
 const showNeedle=w&&['odor','wind'].includes(kind);
 $('needle').classList.toggle('off',!showNeedle);$('compass').classList.toggle('calm',kind==='calm');
 if(w)setNeedle(w.from);
 $('needle').style.color=kind==='odor'?data.types[pred.type][1]:'#64748b';
 $('rose').setAttribute('aria-label',showNeedle?`북쪽 고정 나침반. ${direction(w.from)}쪽에서 들어옴`:'북쪽 고정 나침반. 방향 표시 없음');
 $('direction').textContent=kind==='odor'?`${pred.from_sector}쪽에서 유입 추정`:kind==='wind'?`${direction(w.from)}쪽 바람`:kind==='calm'?'방향 보류':'방향 미확인';
 $('multi').hidden=!(kind==='odor'&&pred?.direction==='여러 방향 가능');
 $('type-label').textContent=kind==='odor'?`${data.types[pred.type][0]} · 추정`:kind==='wind'?'바람':kind==='calm'?'약풍':f?'자료 부족':'자료 없음';
 $('model-badge').textContent=data.model?.ok?'예비 실험·미보정':'추정 보류';
 $('compass-at').textContent=basisTime(f?.at);
 $('timing-label').textContent=forecast?'예보 기준':'선택 시각 기준';
 $('layer-label').textContent=hiddenByFilter(kind,pred)?'선택 유형 없음':(kind==='odor'?`${data.types[pred.type][0]} · 이동 방향`:kind==='wind'?'바람 이동':kind==='calm'?'방향 보류':'방향 미확인')+(forecast?' · 점선 예보':'');
 // Timeline
 const latest=data.latest_index??data.frames.length-1;
 $('time-label').textContent=fmt(f?.at)+(f?' KST':'');
 const stale=f&&index===latest&&(Date.now()-Date.parse(f.at)>3600000);
 const mode=!f?'자료 없음':forecast?data.forecast?.label||'예보':index===latest?(stale?'업데이트 지연':'최신'):'지난 기록';
 $('time-mode').textContent=mode;$('time-mode').className='badge'+(forecast?' forecast':stale?' hold':'');
 $('basis').textContent=forecast?'예보 기준':(f?.basis||'');$('basis').hidden=!f||(!forecast&&!f.basis);
 const ahead=data.frames.length-1-latest;
 $('future').textContent=ahead>0?`예보 ~${fmt(data.frames.at(-1).at)}`:'미래 자료 없음';
 const slider=$('time-slider');slider.max=Math.max(0,data.frames.length-1);slider.value=Math.max(0,index);
 const split=data.frames.length>1?(latest/(data.frames.length-1))*100:100;
 slider.style.setProperty('--split',`${split}%`);slider.classList.toggle('has-forecast',ahead>0);
 slider.setAttribute('aria-valuetext',`${fmt(f?.at)} ${mode}`);
 slider.disabled=!f;$('previous').disabled=index<=0;$('next').disabled=index<0||index>=data.frames.length-1;
 $('play').disabled=data.frames.length<2;$('latest').disabled=!data.frames.length;
 document.querySelectorAll('[data-filter]').forEach(b=>{b.classList.toggle('active',b.dataset.filter===state.filter);b.setAttribute('aria-pressed',String(b.dataset.filter===state.filter));});
 document.querySelectorAll('[data-panel]').forEach(b=>b.classList.toggle('active',b.dataset.panel===state.panel||(b.dataset.panel==='map'&&['zone','flow','info','criteria',''].includes(state.panel))));
 drawZones();drawFlows();renderPanel();
 $('compass').classList.toggle('collapsed',!!state.compass_collapsed);$('compass-toggle').setAttribute('aria-expanded',String(!state.compass_collapsed));
}
function rows(values){return '<dl>'+Object.entries(values).map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')+'</dl>';}
function openPanel(panel){state.panel=panel==='map'?'':panel;render();send();}
function renderPanel(){
 const panel=state.panel,z=nearby(),s=stat(),f=frame(),w=f?.wind,kind=spotKind(),pred=s.pred,forecast=isForecast(f);
 $('panel').hidden=!panel;if(!panel)return;
 let title='',content='';
 const model='<span class="badge model">예비 실험·미보정</span>';
 if(panel==='air'){
  const d=window.appArgs.device||{},enabled=state.auto_enabled!==false;
  const devState=d.connected?`연결됨 · ${d.device_fan===true?'가동 중':d.device_fan===false?'대기 중':'응답 대기'}${d.simulator?' · 시뮬레이터':''}`:(d.status||'연결된 기기 없음');
  const around=!z?'자료 없음':pred?.level?`유입 가능성 ${pred.level} · ${forecast?'예보 기준':basisTime(f?.at)}`:pred?'추정 보류':'자료 없음';
  const judge=!enabled?'사용 안 함':{ON:'가동',OFF:'대기',HOLD:'판단 보류'}[d.action]||'판단 보류';
  const ports=(d.ports||[]).map(p=>`<option ${p===(state.device_port||d.port)?'selected':''}>${esc(p)}</option>`).join('');
  title='공기질 관리';content=rows({'등록 위치':z?.name||'선택 위치 · 관측 구역 밖','주변 상태':around,'전망':z?data.outlook?.[z.id]||'추정 보류':'—'})
   +`<dl><dt>자동 대응</dt><dd><button id="auto-toggle" class="chip ${enabled?'on':''}" aria-pressed="${enabled}">${enabled?'사용 중':'사용 안 함'}</button> <span class="muted">판단 · ${esc(judge)}</span></dd>`
   +`<dt>기기 상태</dt><dd id="device-state">${esc(devState)}</dd>`
   +`<dt>포트</dt><dd class="port-row"><select id="device-port" aria-label="포트">${ports||'<option value="">포트 없음</option>'}</select>`
   +`<button data-device="autodetect">자동 감지</button><button data-device="connect" ${ports?'':'disabled'}>연결</button><button data-device="disconnect" ${d.port?'':'disabled'}>해제</button></dd></dl>`
   +(d.connected&&d.mode==='MANUAL'?`<div class="manual-note" role="status">수동 조작 중 · 자동 대응 일시 중지 <button data-device="auto">자동으로 되돌리기</button></div>`:'')
   +(d.last_error?`<p class="muted">${esc(d.last_error)}</p>`:'')
   +(d.simulator?`<div class="sim"><span class="eyebrow">시뮬레이터 · 실제 기기 아님</span><div><button data-device="sim_short">버튼 짧게</button><button data-device="sim_long">버튼 길게</button><button data-device="sim_unplug">USB 분리</button></div>${(d.lcd||[]).map(p=>`<pre class="lcd">${esc(p[0])}\n${esc(p[1])}</pre>`).join('')}<span class="muted">LED ${d.leds?.green?'초록':'빨강'} · 팬 ${d.leds?.fan?'회전':'정지'}</span></div>`:'')
   +`${model}<details><summary>자세히</summary><p>공기질 관리미 · 모델은 유입 가능성만 추정하고, 켜기·끄기는 규칙이 정합니다. 기기는 받은 명령만 수행합니다.</p><p>켜기: 높음 ${d.streak?.[0]??2}회 연속 · 끄기: 낮음 ${d.streak?.[1]??2}회 연속 · 자료 없음은 판단 보류(직전 상태 유지)</p><p>기기 상태는 기기가 응답한 값입니다.</p></details>`;
 }else if(panel==='record'){
  title='냄새 기록';const url=window.appArgs.measurement_url||'';
  content=/^https?:\/\//.test(url)?`<p>지금 느낀 냄새를 기록하세요.</p><a class="link-button" target="_blank" rel="noopener" href="${esc(url)}">냄새 기록 열기 ↗</a>`:'<p>기록 연결 · 준비 중</p>';
 }else if(panel==='zone'){
  title=z?.name||'선택 위치';content=rows({'위치':state.position_kind==='gps'?'내 위치':'선택 위치','집계 구역':z?'가까운 관측 구역 · 경계 미확정':'관측 구역 밖',
   '관측':forecast?'관측 없음 · 예보':s.status,'감지':s.n?`${s.n}명 중 ${s.detected}명`:'—','최근 제보':(r=>r?`최근 3시간 ${r.count}건${r.device?` · 기기 ${r.device}`:''}`:'없음')(window.appArgs.recent?.[z?.id]),'중앙 강도':s.median??'—',
   '추정':pred?.level?levelLabel(pred):pred?'추정 보류':'—','방향':kind==='calm'?'방향 보류':pred?.direction||'—',
   '기준 시각':fmt(f?.at),'구역 대표점':'임시 위치'})+model+'<button data-open="criteria">집계 기준 ⓘ</button>';
 }else if(panel==='flow'){
  title=kind==='odor'?(forecast?'유입 추정 · 예보':'유입 추정'):'바람 이동';
  const cands=(pred?.candidates||[]).map(c=>`${c.name}(${c.type})`).join(', ');
  content=rows({'유형':kind==='odor'?pred.type_label:'유형 미확인',
   '들어오는 방향':w&&kind!=='calm'?`${direction(w.from)}쪽 · ${w.from}°`:'방향 보류',
   '이동 방향':w&&kind!=='calm'?`${direction(w.to)}쪽 · ${w.to}°`:'방향 보류',
   '방향 판단':kind==='calm'?'방향 보류(약풍)':pred?.direction||'—',
   '정렬 후보':kind==='odor'&&cands?cands:'—','기준 시각':fmt(f?.at),
   '자료 구분':forecast?`예보 · ${data.forecast?.label||''}`:(f?.basis||'—'),'풍속':w?`${w.speed} m/s`:'—'})
   +model+'<details><summary>추정 방향 ⓘ</summary><p>정렬 후보는 방위 일치이며 발생원 판정이 아닙니다.</p><p>화살표 한 방향을 여러 번 그린 참고선입니다. 확산 경로가 아닙니다.</p></details>';
 }else if(panel==='info'){
  title='자료 정보';content=rows(data.info)+`<p><a target="_blank" rel="noopener" href="https://github.com/southkorea/southkorea-maps">경계 출처 ↗</a></p>`;
 }else if(panel==='criteria'){
  title='집계 기준';content='<p>정기·실외 관측 중 냄새 유무를 판단한 응답만 집계합니다. 판단 어려움, 실내, 추가 제보, 대응 후 평가는 분모에서 제외합니다.</p><p>같은 참여자의 같은 구역·시간 기록은 마지막 응답을 사용합니다. 유효 응답 3명 미만은 자료 부족입니다.</p><p>화살표는 추정이 낮고 실제 감지율도 25% 미만이면 바람 이동(회색)만 표시합니다.</p><p>추가 제보와 기기 버튼 제보는 감지율에 넣지 않고 ‘제보’로 따로 표시합니다.</p>';
 }else{
  title='도움말';content='<button data-open="info">자료 정보 →</button><button data-open="criteria">집계 기준 →</button><details><summary>추정 방향</summary><p>지도는 이동 방향, 나침반은 들어오는 방향입니다. 북동풍이면 지도는 남서쪽, 나침반은 북동쪽을 가리킵니다.</p><p>마커 색: 주민 관측 · 화살표: 모델 추정(예비 실험·미보정). 화살표 색은 추정 유형이며 위험 등급이 아닙니다.</p><p>주황 실선: 축산계 · 보라 긴 점선: 하수계 · 회색: 미확인 또는 바람 이동 · 둥근 점선: 예보.</p></details><details><summary>위치 · 개인정보</summary><p>내 위치는 버튼을 눌러 권한을 허용할 때만 확인합니다. 선택 좌표는 조회 계산에만 쓰고 관측 DB에 저장하지 않습니다.</p><p>2km 이내의 가장 가까운 관측 구역을 참고합니다. 건물별 예측이 아닙니다.</p></details><details><summary>시간 · 자료 상태</summary><p>지난 기록은 직접 고른 과거 시각입니다. 최신 자료가 1시간 넘게 오래되면 업데이트 지연입니다.</p><p>최신 이후는 예보 구간입니다. 기상청 연결이 없으면 시연 예보입니다.</p><p>자료 없음·자료 부족·방향 보류는 냄새 없음이 아닙니다.</p></details>';
 }
 $('panel-title').textContent=title;$('panel-content').innerHTML=content;
 $('panel-content').querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>openPanel(b.dataset.open));
 const tog=$('auto-toggle');if(tog)tog.onclick=()=>{state.auto_enabled=state.auto_enabled===false;render();send();};
 const port=$('device-port');if(port)port.onchange=()=>{state.device_port=port.value;};
 $('panel-content').querySelectorAll('[data-device]').forEach(b=>b.onclick=()=>{
  const op=b.dataset.device==='autodetect'?'connect':b.dataset.device;
  state.device_cmd={op,port:b.dataset.device==='connect'?($('device-port')?.value||''):'',id:Date.now()};send();});
}
function stop(){if(timer)clearInterval(timer);timer=null;$('play').textContent='▷';$('play').setAttribute('aria-label','재생');}
function setTime(index){
 const f=data.frames[Math.max(0,Math.min(data.frames.length-1,index))];if(!f)return;
 state.at=f.at;state.mode=f.kind==='forecast'?'forecast':data.frames.indexOf(f)===(data.latest_index??data.frames.length-1)?'latest':'past';
 if(f.kind==='forecast'&&data.forecast?.error)message(`${data.forecast.error} · 시연 예보`);
 render();send();
}
function initialize(args){
 data=args.payload;selection=args.selection;state={position:selection.position,position_kind:'selected',at:selection.at,mode:'latest',filter:'all',panel:'',auto_enabled:true,sequence:0,...args.initial_state};
 const bounds=L.geoJSON(data.boundary).getBounds();
 map=L.map('map',{zoomControl:false,maxBounds:bounds.pad(.10),maxBoundsViscosity:1,minZoom:10,maxZoom:17,zoomSnap:.5}).setView(state.center||[37.654,126.680],state.zoom||13.5);
 tiles=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a>',referrerPolicy:'strict-origin-when-cross-origin'}).addTo(map);
 tiles.on('tileerror',()=>{tileFailures++;if(tileFailures>=2)$('tile-error').hidden=false;});
 tiles.on('tileload',()=>{if(tileFailures===0)$('tile-error').hidden=true;});
 L.geoJSON(data.boundary,{style:{color:'#477ba4',weight:2,fillColor:'#d3e4ed',fillOpacity:.07,dashArray:'6 5'},interactive:false}).addTo(map);
 flows=L.layerGroup().addTo(map);markers=L.layerGroup().addTo(map);
 pin=L.marker(state.position,{icon:L.divIcon({className:'selected-marker',iconSize:[18,18],iconAnchor:[9,9]}),title:'기준 위치',zIndexOffset:1000}).addTo(map).on('click',()=>openPanel('zone'));
 map.on('click',e=>{if(picking)choose([e.latlng.lat,e.latlng.lng]);});
 map.on('moveend',()=>{if(rendered)send();});map.on('zoomend',()=>drawZones());
 $('zoom-in').onclick=()=>map.zoomIn();$('zoom-out').onclick=()=>map.zoomOut();
 $('recenter').onclick=()=>map.stop().setView(state.position,14,{animate:false});$('overview').onclick=()=>map.stop().fitBounds(bounds,{padding:[20,20],animate:false});
 $('pick').onclick=()=>{locationRequest++;picking=!picking;$('pick').classList.toggle('active',picking);if(picking)message('지도에서 위치를 선택하세요');else hideMessage();};
 $('locate').onclick=()=>{
  if(!navigator.geolocation){message('위치 사용 불가 · 지도에서 선택');return;}
  message('위치 확인 중');const request=++locationRequest;
  navigator.geolocation.getCurrentPosition(p=>{if(request!==locationRequest)return;const pos=[p.coords.latitude,p.coords.longitude];if(choose(pos,'gps'))map.setView(pos,14);},()=>{if(request===locationRequest)message('위치 권한 또는 연결 확인 · 지도에서 선택');},{timeout:10000,maximumAge:60000,enableHighAccuracy:false});
 };
 $('retry').onclick=()=>{tileFailures=0;$('tile-error').hidden=true;tiles.redraw();};
 $('time-slider').oninput=e=>{stop();setTime(Number(e.target.value));};
 $('previous').onclick=()=>{stop();setTime(frameIndex()-1);};
 $('next').onclick=()=>{stop();setTime(frameIndex()+1);};
 $('latest').onclick=()=>{stop();hideMessage();setTime(data.latest_index??data.frames.length-1);};
 $('play').onclick=()=>{if(timer){stop();return;}if(state.at===data.frames.at(-1)?.at)setTime(0);$('play').textContent='Ⅱ';$('play').setAttribute('aria-label','정지');timer=setInterval(()=>{const i=frameIndex();if(i>=data.frames.length-1){stop();return;}setTime(i+1);},1800);};
 document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{state.filter=b.dataset.filter;render();send();});
 document.querySelectorAll('[data-panel]').forEach(b=>b.onclick=()=>openPanel(b.dataset.panel));
 $('close-panel').onclick=()=>openPanel('');$('legend-help').onclick=()=>openPanel('flow');
 $('compass-toggle').onclick=()=>{state.compass_collapsed=!state.compass_collapsed;render();send();};
 document.addEventListener('keydown',e=>{if(e.key==='Escape'){stop();picking=false;$('pick').classList.remove('active');hideMessage();openPanel('');}});
 window.addEventListener('resize',()=>{map.invalidateSize();post('streamlit:setFrameHeight',{height:window.innerHeight});});
 rendered=true;render();
}
window.addEventListener('message',event=>{
 if(event.source!==window.parent||event.data?.type!=='streamlit:render')return;
 const args=event.data.args;window.appArgs=args;
 if(!window.L){$('tile-error').hidden=false;$('tile-error').querySelector('strong').textContent='지도 초기화 실패';$('retry').onclick=()=>location.reload();return;}
 if(!map)initialize(args);
 else if((args.selection.sequence||0)>=(state.sequence||0)){
  // A newer local choice wins over an older server echo; the viewed time is never forced to latest.
  data=args.payload;selection=args.selection;state.position=selection.position;state.at=selection.at;render();
 }
 post('streamlit:setFrameHeight',{height:window.innerHeight||900});
});
post('streamlit:componentReady',{apiVersion:1});
// Read-only diagnostics for browser regression tests.
window.odorMap={get state(){return state;},get map(){return map;},get data(){return data;},get needleAngle(){return needleAngle;},deltaAngle,direction,flowLines};
