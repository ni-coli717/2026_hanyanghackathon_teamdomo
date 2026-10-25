'use strict';
// 냄새 나침반 첫 화면. Native Streamlit component protocol. 추정값은 전부 Python(analysis_service)에서 오고 여기서는 보여주기만 한다.
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let data, state, map, tiles, zoneLayer, labelLayer, pin, accuracy, selection, timer=null, picking=false, rendered=false, tileFailures=0, locationRequest=0, arrowAngle=null;
const emptyStat={n:0,detected:0,status:'자료 없음',type:'unknown',odor_evidence:false,median:null,pred:null,arrow:'none'};
const LEVELS=['낮음','보통','높음'];
const LEVEL_CLASS={'낮음':'low','보통':'mid','높음':'high'};
const COLORS={low:'#2E8B57',mid:'#E0A100',high:'#D64533',hold:'#9AA5AE'};
const TABS={now:'지금',forecast:'예보',record:'기록',help:'안내'};
const post=(type,extra={})=>window.parent.postMessage({isStreamlitMessage:true,type,...extra},'*');
function send(){
 if(!map||!state)return;
 state.center=[map.getCenter().lat,map.getCenter().lng];state.zoom=map.getZoom();
 state.sequence=(state.sequence||0)+1;
 post('streamlit:setComponentValue',{value:{...state},dataType:'json'});
}
// ------------------------------------------------------------------ 시간·방향 유틸
function parts(iso){return Object.fromEntries(new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(iso)).map(x=>[x.type,x.value]));}
function fmt(iso){if(!iso)return '자료 없음';const p=parts(iso);return `${p.month}.${p.day} ${p.hour}:${p.minute}`;}
function sameDay(a,b){const p=parts(a),q=parts(b);return p.year===q.year&&p.month===q.month&&p.day===q.day;}
// 오늘이면 '14:00', 아니면 '09.16 22:00'
function shortTime(iso){if(!iso)return '자료 없음';const p=parts(iso);return sameDay(iso,new Date().toISOString())?`${p.hour}:${p.minute}`:fmt(iso);}
function hourWord(iso){const h=Number(parts(iso).hour);const part=h<6?'새벽':h<12?'아침':h<18?'낮':'저녁';return `${part} ${h%12||12}시`;}
function direction(deg){return ['북','북북동','북동','동북동','동','동남동','남동','남남동','남','남남서','남서','서남서','서','서북서','북서','북북서'][Math.round(((deg%360)+360)%360/22.5)%16];}
function direction8(deg){return ['북','북동','동','남동','남','남서','서','북서'][Math.round(((deg%360)+360)%360/45)%8];}
function deltaAngle(a,b){return ((b-a+540)%360)-180;}
function km(a,b){const r=Math.PI/180, dLat=(b[0]-a[0])*r,dLon=(b[1]-a[1])*r;const v=Math.sin(dLat/2)**2+Math.cos(a[0]*r)*Math.cos(b[0]*r)*Math.sin(dLon/2)**2;return 6371.0088*2*Math.atan2(Math.sqrt(v),Math.sqrt(1-v));}
function inRing(lat,lon,ring){let inside=false;for(let i=0,j=ring.length-1;i<ring.length;j=i++){const [x,y]=ring[i],[xx,yy]=ring[j];if((y>lat)!=(yy>lat)&&lon<(xx-x)*(lat-y)/(yy-y)+x)inside=!inside;}return inside;}
function inside(position){return data.boundary.features.some(f=>{const polys=f.geometry.type==='MultiPolygon'?f.geometry.coordinates:[f.geometry.coordinates];return polys.some(r=>inRing(...position,r[0])&&!r.slice(1).some(h=>inRing(...position,h)));});}
// ------------------------------------------------------------------ 선택 상태
function nearby(){let closest=null,best=Infinity;data.zones.forEach(z=>{const dist=km(state.position,[z.lat,z.lon]);if(dist<best){closest=z;best=dist;}});return best<=2?closest:null;}
function frame(){return data.frames.find(f=>f.at===state.at)||null;}
function frameIndex(){return data.frames.findIndex(f=>f.at===state.at);}
function latestIndex(){return data.latest_index??data.frames.length-1;}
function latestFrame(){return data.frames[latestIndex()]||null;}
function isForecast(f=frame()){return f?.kind==='forecast';}
function stat(f=frame(),z=nearby()){return z?f?.zones[z.id]||emptyStat:emptyStat;}
function levelOf(f,zoneId){const p=f?.zones?.[zoneId]?.pred;return p?.level&&LEVELS.includes(p.level)?p.level:null;}
function maxLevel(levels){const ranks=levels.filter(Boolean).map(l=>LEVELS.indexOf(l));return ranks.length?LEVELS[Math.max(...ranks)]:null;}
// '오늘 냄새 날 가능성' = 최신 관측부터 오늘 안의 예보까지 중 가장 높은 단계
function todayLevel(zoneId){
 if(!zoneId||!data.frames.length)return null;
 const li=latestIndex(),today=data.now||new Date().toISOString();
 const span=data.frames.slice(li).filter(f=>sameDay(f.at,today));
 return maxLevel((span.length?span:[data.frames[li]]).map(f=>levelOf(f,zoneId)));
}
// 지금 이후 예보 프레임을 1시간 단위로 6개
function sixHours(zoneId){
 const now=Date.parse(data.now||new Date().toISOString());const out=[];const seen=new Set();
 for(const f of data.frames){
  if(f.kind!=='forecast'||Date.parse(f.at)<=now)continue;
  const h=parts(f.at).hour;if(seen.has(h))continue;seen.add(h);
  out.push({at:f.at,hour:h,level:levelOf(f,zoneId)});if(out.length===6)break;
 }
 return out;
}
function windOf(f){const w=f?.wind;if(!w)return null;return {...w,calm:w.speed<(data.calm_ms??.5)};}
function windText(w){if(!w)return '바람 자료 없음';if(w.calm)return `바람 약함 ${w.speed} m/s · 방향 보류`;return `${direction(w.from)}풍 ${w.speed} m/s · ${direction(w.to)}쪽으로 붐`;}
function message(text){$('notice').textContent=text;$('notice').hidden=false;}
function hideMessage(){$('notice').hidden=true;}
function choose(position,kind='selected'){
 locationRequest++;
 if(!inside(position)){message('김포 밖입니다 · 운양동에서 위치 선택');return false;}
 state.position=position;state.position_kind=kind;picking=false;$('pick').classList.remove('active');hideMessage();render();send();return true;
}
// ------------------------------------------------------------------ 지도
function drawZones(){
 zoneLayer.clearLayers();labelLayer.clearLayers();
 const f=frame(),sel=nearby(),forecast=isForecast(f);
 data.zones.forEach(z=>{
  const level=state.tab==='forecast'?levelOf(f,z.id):todayLevel(z.id);
  const cls=LEVEL_CLASS[level]||'hold',color=COLORS[cls];
  const poly=L.polygon(z.ring,{color,weight:sel?.id===z.id?2.5:1.5,fillColor:color,fillOpacity:cls==='hold'?.16:.28,bubblingMouseEvents:false}).addTo(zoneLayer);
  poly.on('click',()=>{choose([z.lat,z.lon]);openPanel('zone');});
  const s=f?.zones[z.id]||emptyStat,rep=window.appArgs.recent?.[z.id];
  const sub=level||(forecast?'예보 없음':s.status==='자료 없음'?'추정 보류':s.status);
  const html=`<b>${esc(z.name)}</b><i class="lv-${cls}">${esc(sub)}${rep?` · 제보 ${rep.count}`:''}</i>`;
  L.marker([z.lat,z.lon],{icon:L.divIcon({className:'zone-label'+(sel?.id===z.id?' selected':''),html,iconSize:[120,36],iconAnchor:[60,18]}),interactive:false,keyboard:false}).addTo(labelLayer);
 });
 const gps=state.position_kind==='gps';
 pin.setLatLng(state.position).setIcon(L.divIcon({className:gps?'me-dot':'sel-dot',iconSize:gps?[14,14]:[12,12],iconAnchor:gps?[7,7]:[6,6]}));
 accuracy.setLatLng(state.position).setRadius(gps?Math.min(state.accuracy||60,200):0).setStyle({opacity:gps?1:0,fillOpacity:gps?.15:0});
}
// 바람 화살표: 바람이 가는 방향. 최단 호로 돈다 (359° -> 1° 은 2°).
function setArrow(deg){arrowAngle=arrowAngle===null?deg:arrowAngle+deltaAngle(((arrowAngle%360)+360)%360,deg);$('wind-arrow').style.transform=`rotate(${arrowAngle}deg)`;}
// ------------------------------------------------------------------ 화면
function render(){
 const z=nearby(),f=frame(),latest=latestFrame(),w=windOf(f),index=frameIndex(),li=latestIndex(),forecast=isForecast(f);
 $('demo').hidden=!data.demo;
 $('header-at').textContent=latest?`운양동 · ${shortTime(latest.at)}`:'운양동';
 // 바람 버튼
 $('wind-btn').classList.toggle('calm',!w||w.calm);
 $('wind-name').textContent=w?(w.calm?'약풍':direction8(w.from)+'풍'):'—';
 $('wind-speed').textContent=w?`${w.speed}`:'';
 if(w&&!w.calm)setArrow(w.to);
 $('wind-btn').setAttribute('aria-label',w?`바람 ${windText(w)} · 상세`:'바람 자료 없음');
 // 머리: 최신이면 오늘, 과거·예보를 골랐으면 그 시각
 const atLatest=index===li;
 const level=atLatest?todayLevel(z?.id):levelOf(f,z?.id);
 const cls=LEVEL_CLASS[level]||'hold';
 $('level-word').textContent=level||(z?'보류':'—');$('level-word').className=cls;
 $('head-label').textContent=(atLatest?'오늘 냄새 날 가능성':`${fmt(f?.at)} ${forecast?'예보':'기록'}`)+(z?` · ${z.name}`:' · 관측 구역 밖');
 $('head-sub').textContent=z?windText(w):'구역을 누르거나 내 위치를 켜 주세요';
 $('head').setAttribute('aria-expanded',String(!state.collapsed));
 // 앞으로 6시간
 const hours=sixHours(z?.id);
 $('bars').innerHTML=hours.length?hours.map(h=>{const c=LEVEL_CLASS[h.level]||'hold';return `<div class="tile"><span class="t">${esc(h.hour)}시</span><span class="slot"><span class="bar ${c}"></span></span><span class="l lv-${c}">${esc(h.level||'—')}</span></div>`;}).join('')
  :`<p class="muted">${esc(data.forecast?.label||'예보 없음')}${data.forecast?.error?' · '+esc(data.forecast.error):''}</p>`;
 const span=hours.length?Math.round((Date.parse(hours.at(-1).at)-Date.parse(data.now||new Date().toISOString()))/3600000):6;
 $('ahead-title').textContent=!hours.length?'앞으로':span<=8?`앞으로 ${span}시간`:`예보 · ${fmt(hours[0].at)}부터`;
 const peak=maxLevel(hours.map(h=>h.level));const first=hours.find(h=>h.level===peak);
 $('peak').textContent=peak&&first?(peak==='낮음'?'계속 낮음':`${hourWord(first.at)} ${peak}`):'';$('peak').className='peak '+(LEVEL_CLASS[peak]||'');
 $('foot').textContent=`냄새 나침반 v1 · ${latest?shortTime(latest.at):'—'} 갱신`;
 // 탭·시트
 document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===state.tab));
 $('sheet').classList.toggle('collapsed',!!state.collapsed&&state.tab==='now'&&!state.panel);
 $('view-now').hidden=state.tab!=='now'||!!state.panel;$('view-tab').hidden=!$('view-now').hidden;
 drawZones();renderPanel();
 requestAnimationFrame(()=>document.documentElement.style.setProperty('--sheet-h',`${$('sheet').offsetHeight}px`));
}
function rows(values){return '<dl>'+Object.entries(values).map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')+'</dl>';}
function openPanel(panel){state.panel=panel||'';if(panel)state.collapsed=false;render();send();}
function setTab(tab){stop();state.tab=tab;state.panel='';if(tab!=='now')state.collapsed=false;render();send();}
function renderPanel(){
 if($('view-tab').hidden)return;
 const panel=state.panel,z=nearby(),f=frame(),s=stat(),w=windOf(f),pred=s.pred,forecast=isForecast(f);
 let title='',content='';
 $('back').hidden=!panel;
 if(panel==='zone'){
  title=z?.name||'선택 위치';
  const rep=window.appArgs.recent?.[z?.id];
  content=rows({'위치':z?.subtitle||'관측 구역 밖','오늘 가능성':todayLevel(z?.id)||'추정 보류','바람':windText(w),
   '주민 관측':forecast?'관측 없음 · 예보':s.status,'감지':s.n?`${s.n}명 중 ${s.detected}명`:'—','최근 제보':rep?`최근 3시간 ${rep.count}건${rep.device?` · 기기 ${rep.device}`:''}`:'없음',
   '전망':z?data.outlook?.[z.id]||'추정 보류':'—','기준 시각':fmt(f?.at)})+'<div class="menu"><button data-open="criteria">집계 기준</button></div>';
 }else if(panel==='flow'){
  title='바람과 냄새';
  content=rows({'바람':windText(w),'들어오는 쪽':w&&!w.calm?`${direction(w.from)}쪽 · ${w.from}°`:'방향 보류','나가는 쪽':w&&!w.calm?`${direction(w.to)}쪽 · ${w.to}°`:'방향 보류',
   '추정':pred?.level?`${pred.level}${pred.from_sector?` · ${pred.from_sector}쪽에서 유입`:''}`:'추정 보류','자료':forecast?`예보 · ${data.forecast?.label||''}`:(f?.basis||'—'),'기준 시각':fmt(f?.at)})
   +'<p>북쪽에서 바람이 올 때, 습할 때 냄새 제보가 많았습니다. 바람이 발원지 쪽에서 마을로 불면 가능성이 올라갑니다.</p>';
 }else if(panel==='info'){
  title='자료 정보';content=rows(data.info)+`<p><a target="_blank" rel="noopener" href="https://github.com/southkorea/southkorea-maps">경계 출처 ↗</a></p>`;
 }else if(panel==='criteria'){
  title='집계 기준';content='<p>정기·실외 관측 중 냄새 유무를 판단한 응답만 집계합니다. 판단 어려움, 실내, 추가 제보는 분모에서 제외합니다.</p><p>같은 참여자의 같은 구역·시간 기록은 마지막 응답을 사용합니다. 유효 응답 3명 미만은 자료 부족입니다.</p><p>추가 제보와 기기 버튼 제보는 감지율에 넣지 않고 ‘제보’로 따로 표시합니다.</p><p>구역 경계는 가장 가까운 대표점 기준 1.5 km 입니다. 실측 경계가 정해지면 바뀝니다.</p>';
 }else if(panel==='privacy'){
  title='위치 · 개인정보';content='<p>내 위치는 버튼을 눌러 권한을 허용할 때만 확인합니다. 좌표는 조회 계산에만 쓰고 저장하지 않습니다.</p><p>2 km 이내의 가장 가까운 관측 구역을 기준으로 보여줍니다. 건물별 예측이 아닙니다.</p><p>지난 기록은 예보 탭에서 고른 과거 시각입니다. 최신 자료가 1시간 넘게 오래되면 갱신 지연입니다.</p>';
 }else if(panel==='air'){
  const d=window.appArgs.device||{},enabled=state.auto_enabled!==false;
  const devState=d.connected?`연결됨 · ${d.device_fan===true?'가동 중':d.device_fan===false?'대기 중':'응답 대기'}${d.simulator?' · 시뮬레이터':''}`:(d.status||'연결된 기기 없음');
  const judge=!enabled?'사용 안 함':{ON:'가동',OFF:'대기',HOLD:'판단 보류'}[d.action]||'판단 보류';
  const ports=(d.ports||[]).map(p=>`<option ${p===(state.device_port||d.port)?'selected':''}>${esc(p)}</option>`).join('');
  title='공기질 관리 기기';content=rows({'등록 위치':z?.name||'관측 구역 밖','주변 상태':z?(pred?.level?`${pred.level} · ${forecast?'예보':shortTime(f?.at)+' 기준'}`:'추정 보류'):'자료 없음','전망':z?data.outlook?.[z.id]||'추정 보류':'—'})
   +`<dl><dt>자동 대응</dt><dd><button id="auto-toggle" class="chipbtn ${enabled?'on':''}" aria-pressed="${enabled}">${enabled?'사용 중':'사용 안 함'}</button> <span class="muted">판단 · ${esc(judge)}</span></dd>`
   +`<dt>기기 상태</dt><dd id="device-state">${esc(devState)}</dd>`
   +`<dt>포트</dt><dd class="port-row"><select id="device-port" aria-label="포트">${ports||'<option value="">포트 없음</option>'}</select>`
   +`<button data-device="autodetect">자동 감지</button><button data-device="connect" ${ports?'':'disabled'}>연결</button><button data-device="disconnect" ${d.port?'':'disabled'}>해제</button></dd></dl>`
   +(d.connected&&d.mode==='MANUAL'?`<div class="manual-note" role="status">수동 조작 중 · 자동 대응 일시 중지 <button data-device="auto">자동으로 되돌리기</button></div>`:'')
   +(d.last_error?`<p class="muted">${esc(d.last_error)}</p>`:'')
   +(d.simulator?`<div class="sim"><span class="muted">시뮬레이터 · 실제 기기 아님</span><div><button data-device="sim_short">버튼 짧게</button><button data-device="sim_long">버튼 길게</button><button data-device="sim_unplug">USB 분리</button></div>${(d.lcd||[]).map(p=>`<pre class="lcd">${esc(p[0])}\n${esc(p[1])}</pre>`).join('')}<span class="muted">LED ${d.leds?.green?'초록':'빨강'} · 팬 ${d.leds?.fan?'회전':'정지'}</span></div>`:'')
   +`<details><summary>자세히</summary><p>모델은 가능성만 추정하고, 켜기·끄기는 규칙이 정합니다. 기기는 받은 명령만 수행합니다.</p><p>켜기: 높음 ${d.streak?.[0]??2}회 연속 · 끄기: 낮음 ${d.streak?.[1]??2}회 연속 · 자료 없음은 판단 보류(직전 상태 유지)</p></details>`;
 }else if(state.tab==='forecast'){
  title='예보';
  const li=latestIndex(),index=frameIndex(),ahead=data.frames.length-1-li;
  const stale=f&&index===li&&(Date.now()-Date.parse(f.at)>3600000);
  const mode=!f?'자료 없음':forecast?data.forecast?.label||'예보':index===li?(stale?'갱신 지연':'최신'):'지난 기록';
  const zones=data.zones.map(zz=>{const l=levelOf(f,zz.id),c=LEVEL_CLASS[l]||'hold';return `<button data-zone="${zz.id}" class="${z?.id===zz.id?'on':''}"><span class="sw ${c}"></span><b>${esc(zz.name)}</b><span class="s">${esc(zz.subtitle)}</span><span class="lv-${c}">${esc(l||'보류')}</span></button>`;}).join('');
  content=`<div class="timeline"><div class="row"><strong id="time-label">${esc(fmt(f?.at))}</strong><span class="mode ${forecast?'forecast':stale?'stale':''}" id="time-mode">${esc(mode)}</span></div>
   <div class="tl-controls"><button id="previous" aria-label="이전 시각" ${index<=0?'disabled':''}>‹</button><input id="time-slider" type="range" min="0" max="${Math.max(0,data.frames.length-1)}" value="${Math.max(0,index)}" step="1" aria-label="시각" aria-valuetext="${esc(fmt(f?.at))} ${esc(mode)}" ${f?'':'disabled'}><button id="next" aria-label="다음 시각" ${index<0||index>=data.frames.length-1?'disabled':''}>›</button></div>
   <div class="row"><span class="muted">${ahead>0?`예보 ~${esc(fmt(data.frames.at(-1).at))}`:'미래 자료 없음'}${w?` · ${esc(windText(w))}`:''}</span><button id="latest" class="chipbtn" ${index===li?'disabled':''}>최신</button></div></div>
   <div class="zones">${zones}</div><p class="muted">구역을 누르면 지도와 ‘지금’ 탭이 그 구역 기준이 됩니다.</p>`;
 }else if(state.tab==='record'){
  title='냄새 기록';const url=window.appArgs.measurement_url||'';
  content='<p>냄새를 느낀 자리에서 바로 기록하면 지도가 더 정확해집니다. 위치는 기록할 때만 확인합니다.</p>'+(/^https?:\/\//.test(url)?`<a class="primary" target="_blank" rel="noopener" href="${esc(url)}">냄새 기록하기</a>`:'<p class="muted">기록 앱 연결 · 준비 중</p>');
 }else{
  title='안내';
  content=`<div class="menu"><button data-open="info">자료 정보</button><button data-open="criteria">집계 기준</button><button data-open="flow">바람과 냄새</button><button data-open="privacy">위치 · 개인정보</button><button data-open="air">공기질 관리 기기</button></div><p class="muted" id="model-status">${esc(data.model?.ok?(data.model.status||''):`추정 보류 · ${data.model?.reason||''}`)}</p>`;
 }
 $('panel-title').textContent=title;$('panel-content').innerHTML=content;
 $('panel-content').querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>openPanel(b.dataset.open));
 $('panel-content').querySelectorAll('[data-zone]').forEach(b=>b.onclick=()=>{const zz=data.zones.find(x=>x.id===b.dataset.zone);if(zz){choose([zz.lat,zz.lon]);map.panTo([zz.lat,zz.lon]);}});
 const slider=$('time-slider');if(slider)slider.oninput=e=>{stop();setTime(Number(e.target.value));};
 if($('previous'))$('previous').onclick=()=>{stop();setTime(frameIndex()-1);};
 if($('next'))$('next').onclick=()=>{stop();setTime(frameIndex()+1);};
 if($('latest'))$('latest').onclick=()=>{stop();hideMessage();setTime(latestIndex());};
 const tog=$('auto-toggle');if(tog)tog.onclick=()=>{state.auto_enabled=state.auto_enabled===false;render();send();};
 const port=$('device-port');if(port)port.onchange=()=>{state.device_port=port.value;};
 $('panel-content').querySelectorAll('[data-device]').forEach(b=>b.onclick=()=>{
  const op=b.dataset.device==='autodetect'?'connect':b.dataset.device;
  state.device_cmd={op,port:b.dataset.device==='connect'?($('device-port')?.value||''):'',id:Date.now()};send();});
}
function stop(){if(timer)clearInterval(timer);timer=null;}
function setTime(index){
 const f=data.frames[Math.max(0,Math.min(data.frames.length-1,index))];if(!f)return;
 state.at=f.at;state.mode=f.kind==='forecast'?'forecast':data.frames.indexOf(f)===latestIndex()?'latest':'past';
 if(f.kind==='forecast'&&data.forecast?.error)message(`${data.forecast.error} · 시연 예보`);
 render();send();
}
// 시트 끌기: 손잡이·머리에서 위로 30px 넘게 끌면 펼침, 아래로 끌면 접음
function sheetDrag(el){
 let y0=null;
 el.addEventListener('pointerdown',e=>{y0=e.clientY;});
 el.addEventListener('pointerup',e=>{if(y0===null)return;const dy=e.clientY-y0;y0=null;if(dy<-30)expand(true);else if(dy>30)expand(false);});
 el.addEventListener('pointercancel',()=>{y0=null;});
}
function expand(open){state.collapsed=!open;if(!open){state.tab='now';state.panel='';}render();send();}
function initialize(args){
 data=args.payload;selection=args.selection;
 state={position:selection.position,position_kind:'selected',at:selection.at,mode:'latest',tab:'now',panel:'',collapsed:true,auto_enabled:true,sequence:0,...args.initial_state};
 const bounds=L.geoJSON(data.boundary).getBounds();
 map=L.map('map',{zoomControl:false,attributionControl:true,maxBounds:bounds.pad(.10),maxBoundsViscosity:1,minZoom:10,maxZoom:17,zoomSnap:.5});
 if(state.center)map.setView(state.center,state.zoom||14);else map.fitBounds(L.latLngBounds(data.zones.flatMap(z=>z.ring)),{paddingTopLeft:[10,70],paddingBottomRight:[10,170],animate:false});   // 처음엔 세 구역이 시트 위로 다 보이게
 // 네이버 지도 키가 오기 전까지는 OSM 타일을 CSS 로 흐리게(채도·대비 낮춤) 써서 구역 색만 보이게 한다. (Carto 는 키 필요)
 tiles=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a>',referrerPolicy:'strict-origin-when-cross-origin'}).addTo(map);
 tiles.on('tileerror',()=>{tileFailures++;if(tileFailures>=2)$('tile-error').hidden=false;});
 tiles.on('tileload',()=>{if(tileFailures===0)$('tile-error').hidden=true;});
 zoneLayer=L.layerGroup().addTo(map);labelLayer=L.layerGroup().addTo(map);
 accuracy=L.circle(state.position,{radius:0,color:'#2D7FF9',weight:0,fillColor:'#2D7FF9',fillOpacity:0,interactive:false}).addTo(map);
 pin=L.marker(state.position,{icon:L.divIcon({className:'sel-dot',iconSize:[12,12],iconAnchor:[6,6]}),title:'기준 위치',zIndexOffset:1000,keyboard:false}).addTo(map).on('click',()=>openPanel('zone'));
 map.on('click',e=>{if(picking)choose([e.latlng.lat,e.latlng.lng]);});
 map.on('moveend',()=>{if(rendered)send();});
 $('pick').onclick=()=>{locationRequest++;picking=!picking;$('pick').classList.toggle('active',picking);if(picking)message('지도에서 위치를 누르세요');else hideMessage();};
 $('locate').onclick=()=>{
  if(!navigator.geolocation){message('위치 사용 불가 · 지도에서 선택');return;}
  message('위치 확인 중');const request=++locationRequest;
  navigator.geolocation.getCurrentPosition(p=>{if(request!==locationRequest)return;const pos=[p.coords.latitude,p.coords.longitude];state.accuracy=p.coords.accuracy;if(choose(pos,'gps'))map.setView(pos,15);},()=>{if(request===locationRequest)message('위치 권한 또는 연결 확인 · 지도에서 선택');},{timeout:10000,maximumAge:60000,enableHighAccuracy:false});
 };
 $('wind-btn').onclick=()=>openPanel('flow');
 $('retry').onclick=()=>{tileFailures=0;$('tile-error').hidden=true;tiles.redraw();};
 $('head').onclick=()=>expand(!!state.collapsed);
 sheetDrag($('grip'));sheetDrag($('head'));
 $('back').onclick=()=>openPanel('');
 document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>setTab(b.dataset.tab));
 document.addEventListener('keydown',e=>{if(e.key==='Escape'){stop();picking=false;$('pick').classList.remove('active');hideMessage();if(state.panel)openPanel('');else expand(false);}});
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
window.odorMap={get state(){return state;},get map(){return map;},get data(){return data;},get arrowAngle(){return arrowAngle;},deltaAngle,direction,direction8,todayLevel,sixHours,setTab,openPanel};
