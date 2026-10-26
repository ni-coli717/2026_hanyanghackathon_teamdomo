'use strict';
// 냄새 나침반 · 우리 집 공기청정기 카드/설정/연결.
// 서버(Supabase) 함수만 부른다: device_get / device_set / device_pair / device_unpair.
// 브라우저에 저장하는 것: 기기 번호, 이 브라우저 전용 토큰, 집 이름·좌표(서버에는 구역만 보낸다).
(function(){
const KEY='odor.device.v1';
const STALE_MS=5*60000;
function load(){try{return JSON.parse(localStorage.getItem(KEY)||'null');}catch(e){return null;}}
function save(v){try{if(v)localStorage.setItem(KEY,JSON.stringify(v));else localStorage.removeItem(KEY);}catch(e){}}
let cfg=load(),info=null,err='',busy=false,poll=null,msg='',results=[],searching=false,homeMarker=null;
const api=()=>window.appArgs?.device_api||null;
const hm=iso=>{if(!iso)return '—';const p=parts(iso);return `${p.hour}:${p.minute}`;};
const toModel=z=>api()?.zone_map?.[z]||null;
const toApp=u=>Object.entries(api()?.zone_map||{}).find(([,v])=>v===u)?.[0]||null;
async function rpc(name,body){
 const a=api();if(!a?.url||!a?.key)throw new Error('서버 설정 없음');
 const r=await fetch(`${a.url}/rest/v1/rpc/${name}`,{method:'POST',headers:{apikey:a.key,'Content-Type':'application/json'},body:JSON.stringify(body)});
 const t=await r.text();let j=null;try{j=t?JSON.parse(t):null;}catch(e){}
 if(!r.ok){const m=String(j?.message||'');throw new Error(/invalid code/.test(m)?'코드가 맞지 않음':/expired/.test(m)?'코드 만료 · 기기에서 새 코드':/unauthorized/.test(m)?'연결 해제됨':`오류 ${r.status}`);}
 return j;
}
async function refresh(){
 if(!cfg)return;
 try{info=await rpc('device_get',{p_device:cfg.id,p_token:cfg.token});err='';}
 catch(e){err=e.message;if(err==='연결 해제됨'){cfg=null;info=null;save(null);}}
 renderCard();
}
function startPoll(){if(poll||!cfg)return;poll=setInterval(()=>{if(!document.hidden)refresh();},60000);}
async function setDevice(extra,note){
 if(!cfg||busy)return;busy=true;msg='';renderCard();
 try{await rpc('device_set',{p_device:cfg.id,p_token:cfg.token,...extra});msg=note||'저장됨';await refresh();}
 catch(e){msg=e.message;}
 busy=false;renderCard();if(state.panel==='device')renderPanel();
}
// ------------------------------------------------------------------ 카드 상태
function view(){
 if(!info)return {label:err?'확인 안 됨':'확인 중',pill:'grey',title:err?'연결 확인 안 됨':'—',cls:err?'warn':'',why:err,row:null,foot:''};
 const p=info.plan,s=info.status,set=info.settings||{},now=Date.parse(info.now)||Date.now();
 const seen=s?.seen_at?Date.parse(s.seen_at):null;
 const foot=[seen?`응답 ${hm(s.seen_at)}`:'기기 응답 기록 없음',p?`예보 ${hm(p.computed_at)}`:null,p?.basis==='demo'?'시연':null].filter(Boolean).join(' · ');
 if(seen&&now-seen>STALE_MS)return {label:'응답 없음',pill:'warn',title:'연결 끊김',cls:'warn',why:'전원 · 와이파이 확인',row:['마지막 응답',`${hm(s.seen_at)} (${Math.round((now-seen)/60000)}분 전)`],foot};
 if(info.source==='manual'){const on=set.mode==='on';return {label:on?'수동 가동':'수동 정지',pill:on?'solid':'grey',title:set.manual_until?`${hm(set.manual_until)}까지`:'수동',cls:'',why:'이후 자동',row:null,foot};}
 if(!p||p.state==='hold')return {label:'판단 보류',pill:'dashed',title:p?'예보 없음':'일정 없음',cls:'muted',why:'직전 상태 유지',row:p?['마지막 계산',hm(p.computed_at)]:null,foot};
 const eps=p.episodes||[];
 const active=eps.find(e=>Date.parse(e.on_at)<=now&&now<Date.parse(e.off_at));
 const next=eps.find(e=>Date.parse(e.on_at)>now);
 const ep=active||next;
 const why=ep?`${hm(ep.odor_start)} ${ep.peak_level}${ep.wind_sector?` · ${ep.wind_sector}풍`:''}`:'';
 const row=ep?['가동 구간',`${hm(ep.on_at)} – ${hm(ep.off_at)}`]:null;
 if(active)return {label:'가동 중',pill:'solid',title:`${hm(active.off_at)}까지`,cls:'',why,row,foot};
 if(next)return {label:'가동 예정',pill:'outline',title:`${hm(next.on_at)} 가동`,cls:'',why,row,foot};
 return {label:'대기',pill:'grey',title:'예정 없음',cls:'',why:`${set.trigger_level==='보통'?'보통 이상':'높음'} 예상 없음`,row:null,foot};
}
function cells(){
 const z=toApp(info?.settings?.zone_id);if(!z||typeof sixHours!=='function')return '';
 const hours=sixHours(z);if(!hours.length)return '';
 return `<div class="dev-cells">${hours.map(h=>`<span class="c ${LEVEL_CLASS[h.level]||'hold'}" title="${esc(h.hour)}시 ${esc(h.level||'—')}"></span>`).join('')}</div><div class="dev-hours">${hours.map(h=>`<span>${esc(h.hour)}</span>`).join('')}</div>`;
}
const GEAR='<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3.2" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
function renderCard(){
 const el=$('device-card');if(!el)return;
 drawHome();
 if(!cfg||!api()){el.hidden=true;el.innerHTML='';return;}
 const v=view(),mode=info?.settings?.mode||'auto',name=info?.settings?.name||'우리 집 공기청정기';
 el.hidden=false;
 el.innerHTML=`<div class="dev-top"><strong>${esc(name)}</strong><span class="pill ${v.pill}">${esc(v.label)}</span></div>
  <div class="dev-main"><span class="dev-title ${v.cls}">${esc(v.title)}</span><span class="dev-why">${esc(v.why)}</span></div>
  ${cells()}
  ${v.row?`<div class="dev-row"><span>${esc(v.row[0])}</span><b>${esc(v.row[1])}</b></div>`:''}
  <div class="dev-ctrl"><div class="seg" role="group" aria-label="동작 방식">${[['auto','자동'],['on','켬'],['off','끔']].map(([k,t])=>`<button data-mode="${k}" aria-pressed="${mode===k}" ${busy?'disabled':''}>${t}</button>`).join('')}</div>
  <button class="gear" data-dev-open="device" aria-label="기기 설정">${GEAR}</button></div>
  <div class="dev-foot">${esc(msg||v.foot)}</div>`;
 el.querySelectorAll('[data-mode]').forEach(b=>b.onclick=e=>{e.stopPropagation();setDevice({p_mode:b.dataset.mode},b.dataset.mode==='auto'?'자동':'2시간 뒤 자동');});
 el.querySelector('[data-dev-open]').onclick=e=>{e.stopPropagation();openPanel('device');};
}
function drawHome(){
 if(!window.map||!window.L)return;
 const h=cfg?.home;
 if(!h){if(homeMarker){homeMarker.remove();homeMarker=null;}return;}
 const icon=L.divIcon({className:'home-pin',html:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 11l8-7 8 7v9h-5v-6H9v6H4z" fill="#222" stroke="#fff" stroke-width="1.5"/></svg>',iconSize:[24,24],iconAnchor:[12,20]});
 if(!homeMarker)homeMarker=L.marker([h.lat,h.lon],{icon,interactive:false,keyboard:false,zIndexOffset:900}).addTo(map);
 else homeMarker.setLatLng([h.lat,h.lon]);
}
// ------------------------------------------------------------------ 집 위치 → 구역
function zoneFor(lat,lon){
 let best=null,dist=Infinity;
 (data?.zones||[]).forEach(z=>{const d=km([lat,lon],[z.lat,z.lon]);if(d<dist){dist=d;best=z;}});
 return best&&dist<=1.5?best:null;
}
function setHome(label,lat,lon){
 const z=zoneFor(lat,lon);
 if(!z){msg='관측 구역 밖 · 운양동 안에서 선택';results=[];renderPanel();return;}
 cfg={...cfg,home:{label,lat,lon,zone:z.id}};save(cfg);results=[];
 setDevice({p_zone:toModel(z.id)},`${z.name} · 저장됨`);
}
async function searchHome(q){
 q=(q||'').trim();if(!q)return;searching=true;msg='';renderPanel();
 try{
  const u=`https://nominatim.openstreetmap.org/search?format=jsonv2&countrycodes=kr&limit=6&accept-language=ko&bounded=1&viewbox=126.60,37.71,126.76,37.61&q=${encodeURIComponent(q)}`;
  const r=await fetch(u,{headers:{'Accept':'application/json'}});
  const j=r.ok?await r.json():[];
  results=j.map(x=>({label:(x.name||x.display_name.split(',')[0]).trim(),sub:x.display_name.split(',').slice(1,3).join(',').trim(),lat:+x.lat,lon:+x.lon}));
  if(!results.length)msg='검색 결과 없음 · 지도에서 선택';
 }catch(e){results=[];msg='검색 안 됨 · 지도에서 선택';}
 searching=false;renderPanel();
}
// ------------------------------------------------------------------ 패널
const panels={
 pair(){
  return {title:'공기청정기 연결',content:`<div class="pair-hint"><pre class="lcd" aria-hidden="true">PAIR AP01\nCODE 482 915</pre><div><b>기기 버튼 3초</b><span class="muted">코드 유효 10분</span></div></div>
   <label class="field-label" for="dev-id">기기 번호</label><input id="dev-id" class="field" autocomplete="off" autocapitalize="characters" placeholder="AP01" value="${esc(cfg?.id||'')}">
   <span class="field-label" id="code-label">연결 코드</span><div class="code-boxes" role="group" aria-labelledby="code-label">${[1,2,3,4,5,6].map(i=>`<input class="code-box" inputmode="numeric" maxlength="1" aria-label="${i}번째 숫자">`).join('')}</div>
   <button id="pair-go" class="primary-btn" ${busy?'disabled':''}>연결하기</button><p class="dev-msg" role="status">${esc(msg)}</p>`};
 },
 device(){
  const s=info?.settings||{},home=cfg?.home,zName=(data?.zones||[]).find(z=>z.id===(home?.zone||toApp(s.zone_id)))?.name;
  const seg=(name,opts,cur)=>`<div class="seg" role="radiogroup" aria-label="${name}">${opts.map(([v,t])=>`<button role="radio" data-${name==='가동 시작'?'lead':'trigger'}="${v}" aria-checked="${String(cur)===String(v)}">${t}</button>`).join('')}</div>`;
  return {title:'기기 설정',content:`
   <label class="field-label" for="dev-name">기기 이름</label><input id="dev-name" class="field" value="${esc(s.name||'우리 집 공기청정기')}">
   <label class="field-label" for="home-q">우리 집</label>
   <form id="home-form" class="search-row"><input id="home-q" class="field" placeholder="아파트·도로명 검색" value="${esc(home?.label||'')}"><button type="submit" ${searching?'disabled':''}>검색</button></form>
   ${results.length?`<div class="results">${results.map((r,i)=>`<button data-result="${i}"><b>${esc(r.label)}</b><span class="muted">${esc(r.sub)}</span></button>`).join('')}</div>`:''}
   <div class="zone-row"><span>구역</span><b>${esc(zName||'미정')}</b><span class="muted">${home?'자동':''}</span><button id="home-map" class="link">지도에서 선택</button></div>
   <span class="field-label">가동 시작</span>${seg('가동 시작',[[20,'20분 전'],[40,'40분 전'],[60,'60분 전']],s.lead_min??40)}
   <span class="field-label">가동 기준</span>${seg('가동 기준',[['높음','높음'],['보통','보통 이상']],s.trigger_level||'높음')}
   <dl class="dev-list"><dt>수동 조작 유지</dt><dd>2시간</dd><dt>기기 번호</dt><dd>${esc(cfg?.id||'—')}</dd></dl>
   <button id="unpair" class="danger">연결 해제</button><p class="dev-msg" role="status">${esc(msg)}</p>`};
 }
};
function bind(panel){
 const root=$('panel-content');
 if(panel==='pair'){
  const boxes=[...root.querySelectorAll('.code-box')];
  boxes.forEach((b,i)=>{
   b.oninput=()=>{b.value=b.value.replace(/\D/g,'').slice(-1);if(b.value&&boxes[i+1])boxes[i+1].focus();};
   b.onkeydown=e=>{if(e.key==='Backspace'&&!b.value&&boxes[i-1])boxes[i-1].focus();};
   b.onpaste=e=>{const t=(e.clipboardData.getData('text')||'').replace(/\D/g,'').slice(0,6);if(!t)return;e.preventDefault();t.split('').forEach((c,k)=>{if(boxes[k])boxes[k].value=c;});boxes[Math.min(t.length,5)].focus();};
  });
  $('pair-go').onclick=async()=>{
   const id=($('dev-id').value||'').trim().toUpperCase(),code=boxes.map(b=>b.value).join('');
   if(!id||code.length!==6){msg='기기 번호와 6자리 코드';renderPanel();return;}
   busy=true;msg='';
   try{const token=await rpc('device_pair',{p_device:id,p_code:code});cfg={id,token,home:null};save(cfg);startPoll();await refresh();busy=false;openPanel('device');}
   catch(e){busy=false;msg=e.message;renderPanel();}
  };
 }else if(panel==='device'){
  const name=$('dev-name');name.onchange=()=>setDevice({p_name:name.value},'이름 저장됨');
  $('home-form').onsubmit=e=>{e.preventDefault();searchHome($('home-q').value);};
  root.querySelectorAll('[data-result]').forEach(b=>b.onclick=()=>{const r=results[+b.dataset.result];setHome(r.label,r.lat,r.lon);map.setView([r.lat,r.lon],15);});
  $('home-map').onclick=()=>{api_.pickingHome=true;state.panel='';state.collapsed=true;render();message('지도에서 우리 집을 누르세요');};
  root.querySelectorAll('[data-lead]').forEach(b=>b.onclick=()=>setDevice({p_lead:+b.dataset.lead},'저장됨 · 15분 안에 반영'));
  root.querySelectorAll('[data-trigger]').forEach(b=>b.onclick=()=>setDevice({p_trigger:b.dataset.trigger},'저장됨 · 15분 안에 반영'));
  $('unpair').onclick=async()=>{try{await rpc('device_unpair',{p_device:cfg.id,p_token:cfg.token});}catch(e){}cfg=null;info=null;save(null);msg='';openPanel('');setTab('help');};
 }
}
function homePicked(latlng){
 api_.pickingHome=false;hideMessage();
 setHome('지도에서 선택',latlng.lat,latlng.lng);
 openPanel('device');
}
const api_={pickingHome:false,renderCard,panels,bind,homePicked,refresh,get paired(){return !!cfg;},get info(){return info;}};
window.odorDevice=api_;
if(cfg){refresh();startPoll();}
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&cfg)refresh();});
})();
