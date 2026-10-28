'use strict';
// 냄새 나침반 v3 · 계정 화면(로그인·가입·사용법), ＋기록 흐름, 참여·계정·안내 탭, 우리 집 기기 시트.
// 서버와의 약속: 브라우저는 명령(auth_cmd / record_cmd)만 보내고, 판정·저장은 전부 Python 이 한다.
(function(){
const AUTH_KEY='odor.auth.v1';              // {refresh}: 이메일 로그인 유지용. 토큰 하나뿐, 키·비밀번호는 저장 안 함
const MAX_ACC=150,MAX_DIST_KM=1.5;          // core/geo_check 와 같은 값(표시용). 판정은 서버가 다시 한다
const SCHED=['07:30','12:30','18:30','22:00'];
let acct={status:'anon'},screen='',prev='login',emailMode='login',tut=0,pending=0,cmdSeq=0,tutReplay=false;
let rec=null,recMarker=null,resumeTried=false;
const reduced=()=>window.matchMedia('(prefers-reduced-motion: reduce)').matches;
// 이메일 로그인 유지: localStorage + 같은 주소의 쿠키. 쿠키는 서버가 첫 실행에서 바로 읽어(st.context.cookies) '로그인 확인 중' 왕복을 줄인다.
const stor={get(){try{return JSON.parse(localStorage.getItem(AUTH_KEY)||'null');}catch(e){return null;}},
 set(v){try{if(v)localStorage.setItem(AUTH_KEY,JSON.stringify(v));else localStorage.removeItem(AUTH_KEY);}catch(e){}
  try{document.cookie='odor_refresh='+(v?encodeURIComponent(v.refresh):'')+'; path=/; max-age='+(v?2592000:0)+'; SameSite=Lax';}catch(e){}}};
const hm=iso=>{if(!iso)return '—';const p=parts(iso);return `${p.hour}:${p.minute}`;};
function cmd(kind,body){
 if(!state)state={sequence:0};
 const id=Date.now()*10+(++cmdSeq%10);
 state[kind]={id,...body};pending=id;send();return id;
}
const authCmd=b=>cmd('auth_cmd',b);
// ------------------------------------------------------------------ 화면 전환
function showScreen(name,dir='fwd'){
 const auth=$('auth');auth.hidden=false;
 auth.querySelectorAll('.screen').forEach(s=>{const on=s.id==='s-'+name;if(on&&s.hidden){s.hidden=false;s.classList.remove('in-fwd','in-back');if(!reduced())s.classList.add(dir==='back'?'in-back':'in-fwd');}else if(!on)s.hidden=true;});
 if(screen&&screen!==name&&name!=='doc')prev=screen;
 screen=name;
 if(name==='tutorial')renderTutorial();
 if(name==='email'){$('em-mail').focus?.();}
}
function hideAuth(){$('auth').hidden=true;screen='';}
function msg(id,t){const el=$(id);if(el)el.textContent=t||'';}
function setBusy(on){document.querySelectorAll('#auth .primary-btn,#auth .auth-btn').forEach(b=>b.disabled=!!on);}
// ------------------------------------------------------------------ 계정 상태 반영
function applyAccount(a){
 acct=a||{status:'anon'};
 if(acct.refresh!==undefined){stor.set(acct.refresh?{refresh:acct.refresh}:null);}
 if(acct.cmd_done&&acct.cmd_done>=pending){pending=0;setBusy(false);}
 if(acct.status==='anon'){
  const saved=stor.get();
  if(saved?.refresh&&!resumeTried&&acct.providers?.email){resumeTried=true;showScreen('login');msg('login-msg','로그인 확인 중');authCmd({op:'resume',refresh:saved.refresh});return;}
  if(!acct.providers?.email)stor.set(null);
  if(!tutReplay){if(screen!=='email'&&screen!=='doc')showScreen('login');}
  $('login-kakao').hidden=!acct.providers?.kakao;$('login-google').hidden=!acct.providers?.google;$('login-email').hidden=!acct.providers?.email;
  const none=!acct.providers?.kakao&&!acct.providers?.google&&!acct.providers?.email;
  msg(screen==='email'?'email-msg':'login-msg',acct.notice||(none?'로그인 준비 중 · 운영자가 설정하면 열립니다':''));
  if(acct.notice&&screen==='email')setBusy(false);
  return;
 }
 if(acct.status==='signup'){
  if(screen!=='signup'&&screen!=='doc'){showScreen('signup');$('signup-via').textContent=acct.provider_name?`${acct.provider_name} 계정`:'';if(acct.name&&!$('su-nick').value)$('su-nick').value=acct.name.slice(0,20);}
  msg('signup-msg',acct.notice||'');return;
 }
 if(acct.status==='tutorial'){if(screen!=='tutorial'){tut=0;tutReplay=false;showScreen('tutorial');}return;}
 // ok
 if(!tutReplay)hideAuth();
}
// ------------------------------------------------------------------ 로그인 · 가입
function bindAuth(){
 $('login-kakao').onclick=()=>{msg('login-msg','카카오로 이동 중');setBusy(true);authCmd({op:'login',provider:'kakao'});};
 $('login-google').onclick=()=>{msg('login-msg','구글로 이동 중');setBusy(true);authCmd({op:'login',provider:'google'});};
 $('login-email').onclick=()=>{msg('email-msg','');showScreen('email');};
 document.querySelectorAll('[data-back]').forEach(b=>b.onclick=()=>showScreen(b.dataset.back==='prev'?(prev||'login'):b.dataset.back,'back'));
 document.querySelectorAll('[data-doc]').forEach(b=>b.onclick=()=>openDoc(b.dataset.doc));
 document.querySelectorAll('.tabs2 [role=tab]').forEach(t=>t.onclick=()=>setEmailMode(t.dataset.mode));
 $('email-form').onsubmit=e=>{
  e.preventDefault();const mail=$('em-mail').value.trim(),pw=$('em-pw').value;
  if(!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(mail)){msg('email-msg','이메일 주소 확인');return;}
  if(pw.length<8){msg('email-msg','비밀번호 8자 이상');return;}
  msg('email-msg',emailMode==='login'?'로그인 중':'가입 중');setBusy(true);
  authCmd({op:emailMode==='login'?'email_login':'email_signup',email:mail,password:pw});
  $('em-pw').value='';
 };
 const boxes=()=>[...document.querySelectorAll('[data-consent]')];
 $('c-all').onchange=()=>boxes().forEach(b=>b.checked=$('c-all').checked);
 boxes().forEach(b=>b.onchange=()=>{$('c-all').checked=boxes().every(x=>x.checked);});
 $('su-code-toggle').onclick=()=>{$('su-code-row').hidden=!$('su-code-row').hidden;if(!$('su-code-row').hidden)$('su-code').focus();};
 $('signup-go').onclick=()=>{
  const nick=$('su-nick').value.trim(),consents=boxes().filter(b=>b.checked).map(b=>b.dataset.consent);
  if(nick.length<2){msg('signup-msg','닉네임 2자 이상');$('su-nick').focus();return;}
  if(!['terms','privacy','location'].every(c=>consents.includes(c))){msg('signup-msg','필수 동의를 확인해 주세요');return;}
  msg('signup-msg','저장 중');setBusy(true);
  authCmd({op:'signup',nickname:nick,consents,code:$('su-code-row').hidden?'':$('su-code').value.trim().toUpperCase()});
 };
 $('tut-next').onclick=()=>{if(tut<3){tut++;renderTutorial('fwd');}else finishTutorial();};
 $('tut-prev').onclick=()=>{if(tut>0){tut--;renderTutorial('back');}};
 $('tut-skip').onclick=finishTutorial;
}
function setEmailMode(m){emailMode=m;document.querySelectorAll('.tabs2 [role=tab]').forEach(t=>t.setAttribute('aria-selected',String(t.dataset.mode===m)));document.querySelector('.tabs2 .thumb').style.transform=m==='login'?'translateX(0)':'translateX(100%)';$('email-go').textContent=m==='login'?'로그인':'다음';$('em-pw').autocomplete=m==='login'?'current-password':'new-password';}
const DOCS={
 terms:['이용약관','<p>냄새 나침반은 김포 운양동 주민이 냄새를 기록하고 예보를 보는 참여형 서비스입니다.</p><p>기록은 연구·예보 개선과 지역 공유 자료로 쓰이며, 개인을 알 수 있는 형태로 공개하지 않습니다.</p><p>허위 기록·반복 기록은 집계에서 제외될 수 있습니다. 서비스는 예고 없이 바뀌거나 중단될 수 있습니다.</p>'],
 privacy:['개인정보 처리방침','<p><b>수집 항목</b> 로그인 계정 식별자, 이메일(가린 형태로 표시), 닉네임, 기록할 때의 위치(약 100 m 단위로 반올림), 기록 내용.</p><p><b>이용 목적</b> 기록 저장과 본인 확인, 구역 판정, 예보 계산.</p><p><b>보관</b> 계정 삭제를 요청하면 계정 정보는 지우고 기록은 익명으로 남습니다.</p><p><b>제3자</b> 우리 집 검색은 OpenStreetMap 에 검색어만 보냅니다. 그 밖에 외부로 보내지 않습니다.</p>'],
};
function openDoc(k){const d=DOCS[k];if(!d)return;$('doc-title').textContent=d[0];$('doc-body').innerHTML=d[1];showScreen('doc');}
// ------------------------------------------------------------------ 사용법 4장
const TUT=[
 {h:'색 = 냄새 날 가능성',s:'구역 3곳 · 앞으로 6시간',art:`<svg viewBox="0 0 350 400" aria-hidden="true"><path d="M0 30 C80 50 200 14 350 44 L350 0 L0 0 Z" fill="#CFE0EC"/>
  <path class="a-fade d1" d="M50 170 C30 90 110 50 180 54 C260 58 300 120 270 165 C225 190 110 198 50 170 Z" fill="rgba(214,69,51,0.28)" stroke="#D64533" stroke-width="1.5"/>
  <path class="a-fade d3" d="M50 170 C110 198 225 190 270 165 C280 215 270 245 245 255 C180 265 100 260 62 248 C48 220 46 195 50 170 Z" fill="rgba(224,161,0,0.28)" stroke="#E0A100" stroke-width="1.5"/>
  <path class="a-fade d5" d="M62 248 C100 260 180 265 245 255 C270 300 255 360 190 378 C125 388 70 360 62 318 C58 290 58 268 62 248 Z" fill="rgba(46,139,87,0.28)" stroke="#2E8B57" stroke-width="1.5"/></svg>
  <div class="tut-card a-up d7"><div class="tut-legend"><span class="lv-low">■ 낮음</span><span class="lv-mid">■ 보통</span><span class="lv-high">■ 높음</span></div>
  <div class="tut-bars">${[['low',10,8],['high',30,9],['high',30,10],['mid',20,11],['low',10,12],['low',10,13]].map(([c,h,d])=>`<i class="${c} a-grow d${d}" style="height:${h}px"></i>`).join('')}</div></div>`},
 {h:'두 번 누르면 기록 끝',s:'안 나요는 한 번에 저장',art:`<div class="tut-form">
  <b class="a-up d1">지금 냄새가 나요?</b>
  <div class="two a-up d2"><span class="dark tap">나요<i class="ripple"></i></span><span>안 나요</span></div>
  <b class="a-up d5" style="margin-top:8px">얼마나?</b>
  <div class="three"><span class="a-pop d6">1</span><span class="a-pop d7 pick">2</span><span class="a-pop d8">3</span></div></div>`},
 {h:'하루 4번 정기 관측',s:'그 외 시간은 수시 제보',art:`<div class="tut-form">
  <div class="two"><div class="tcard a-up d1"><span>아침</span><b>07:30</b></div><div class="tcard dark a-up d2 ring"><span>점심</span><b>12:30</b></div><div class="tcard a-up d3"><span>저녁</span><b>18:30</b></div><div class="tcard a-up d4"><span>밤</span><b>22:00</b></div></div>
  <div class="trow a-up d5"><span>앞뒤 15분</span><b>정기 관측</b></div>
  <div class="trow a-up d6"><span>안 나요도 기록</span><b class="lv-low">예보 정확도 ↑</b></div></div>`},
 {h:'위치와 우리 집',s:'기록 위치 확인 · 우리 집 구역 예보',art:`<svg viewBox="0 0 350 400" aria-hidden="true"><path d="M0 30 C80 50 200 14 350 44 L350 0 L0 0 Z" fill="#CFE0EC"/>
  <path d="M50 170 C30 90 110 50 180 54 C260 58 300 120 270 165 C225 190 110 198 50 170 Z" fill="rgba(45,127,249,0.05)" stroke="#9AA5AE"/>
  <path class="a-fade d9" d="M50 170 C110 198 225 190 270 165 C280 215 270 245 245 255 C180 265 100 260 62 248 C48 220 46 195 50 170 Z" fill="rgba(45,127,249,0.16)" stroke="#2D7FF9" stroke-width="2"/>
  <path d="M62 248 C100 260 180 265 245 255 C270 300 255 360 190 378 C125 388 70 360 62 318 C58 290 58 268 62 248 Z" fill="rgba(45,127,249,0.05)" stroke="#9AA5AE"/></svg>
  <span class="tut-dot pulse"></span><span class="tut-dot a-pop d2"></span>
  <div class="tut-search"><div class="a-up d3">반도유보라</div><div class="res a-up d5"><b>운양동 반도유보라 6차</b><span>구역 운양역</span></div></div>
  <div class="tut-home a-pop d11"><span>우리 집 구역</span><b>운양역</b></div>`},
];
function renderTutorial(dir){
 const t=TUT[tut];$('tut-num').textContent=`사용법 ${tut+1} / 4`;
 const stage=$('tut-stage');stage.innerHTML=`<div class="tut-slide ${reduced()?'':dir==='back'?'in-back':'in-fwd'}"><div class="tut-art">${t.art}</div><div class="tut-text a-up d2"><h1>${esc(t.h)}</h1><span>${esc(t.s)}</span></div></div>`;
 $('tut-dots').innerHTML=[0,1,2,3].map(i=>`<span class="${i===tut?'on':''}"></span>`).join('');
 $('tut-prev').hidden=tut===0;$('tut-next').textContent=tut===3?'시작하기':'다음';
}
function finishTutorial(){
 if(tutReplay){tutReplay=false;hideAuth();return;}
 authCmd({op:'tutorial_done'});hideAuth();
}
function replayTutorial(){tutReplay=true;tut=0;showScreen('tutorial');}
// ------------------------------------------------------------------ 정기 관측 칩
function nextScheduled(){
 const now=new Date();const p=parts(now.toISOString());const cur=Number(p.hour)*60+Number(p.minute);
 for(const s of SCHED){const [h,m]=s.split(':').map(Number);const t=h*60+m;if(t+15>=cur)return {label:s,minutes:t-cur};}
 const [h,m]=SCHED[0].split(':').map(Number);return {label:SCHED[0],minutes:h*60+m+1440-cur};
}
function renderChip(){
 const el=$('sched-chip');if(!el||!data)return;
 const n=nextScheduled();el.hidden=false;el.querySelector('b').textContent=n.label;
 const live=n.minutes<=15;el.classList.toggle('live',live);
 el.childNodes[1].textContent=live?'정기 관측 중 ':'다음 정기 관측 ';
}
// ------------------------------------------------------------------ ＋ 기록
function openRecord(){
 rec={step:'locate',loc:null,context:'outdoor',odor:null,intensity:null,unverified:false,error:''};
 $('rec-dim').hidden=false;$('rec').hidden=false;$('rec').classList.remove('out');
 renderRecord();locate();
}
function closeRecord(){
 if(!rec)return;
 const done=()=>{$('rec').hidden=true;$('rec-dim').hidden=true;rec=null;};
 if(reduced()){done();return;}
 $('rec').classList.add('out');setTimeout(done,320);
}
function locate(){
 rec.step='locate';renderRecord();
 if(!navigator.geolocation){rec.loc={status:'none',reason:'이 기기에서 위치를 쓸 수 없음'};rec.step='unverified';renderRecord();return;}
 navigator.geolocation.getCurrentPosition(p=>{
  if(!rec||rec.step!=='locate')return;
  const lat=p.coords.latitude,lon=p.coords.longitude,acc=Math.round(p.coords.accuracy||0);
  let best=null,dist=Infinity;(data?.zones||[]).forEach(z=>{const d=km([lat,lon],[z.lat,z.lon]);if(d<dist){dist=d;best=z;}});
  const ok=acc<=MAX_ACC&&dist<=MAX_DIST_KM;
  rec.loc={status:ok?'verified':'rejected',lat,lon,acc,zone:best,dist};
  if(ok){rec.step='ask';if(map)map.panTo([lat,lon]);}else rec.step='unverified';
  renderRecord();
 },()=>{if(!rec||rec.step!=='locate')return;rec.loc={status:'none',reason:'위치 권한 또는 연결 확인'};rec.step='unverified';renderRecord();},{timeout:12000,maximumAge:30000,enableHighAccuracy:true});
}
function chipText(){
 const l=rec.loc;if(!l)return '<span class="dot pulse"></span>위치 확인 중';
 if(l.status==='verified')return `<span class="dot"></span>${esc(l.zone.name)} · 위치 확인 ±${l.acc} m`;
 return '<span class="dot warn"></span>위치 미확인 · 집계 제외';
}
function modeText(){return nextScheduled().minutes<=15?'정기 관측':'수시 제보';}
function renderRecord(){
 if(!rec)return;const b=$('rec-body');const s=rec.step;
 const head=(title,close=true)=>`<div class="rec-head"><strong>${esc(title)}</strong><span class="muted">${esc(hm(new Date().toISOString()))}</span>${close?'<button class="x" data-rec="close" aria-label="닫기">✕</button>':''}</div>`;
 if(s==='locate'||s==='ask'){
  b.innerHTML=head('기록')+`<div class="rec-chip"><span>${chipText()}</span><span class="muted">${esc(modeText())}</span></div>
   <h2 class="a-up d1">지금 냄새가 나요?</h2>
   <div class="two big"><button class="dark a-pop d2" data-rec="yes" ${s==='locate'?'disabled':''}>나요</button><button class="a-pop d3" data-rec="no" ${s==='locate'?'disabled':''}>안 나요</button></div>
   <div class="rec-row a-up d4"><span>장소</span><div class="seg2" role="radiogroup" aria-label="장소"><span class="thumb" style="transform:translateX(${rec.context==='indoor'?'100%':'0'})"></span><button role="radio" aria-checked="${rec.context==='outdoor'}" data-ctx="outdoor">실외</button><button role="radio" aria-checked="${rec.context==='indoor'}" data-ctx="indoor">실내</button></div><button class="link-btn" data-rec="unsure" ${s==='locate'?'disabled':''}>모르겠어요</button></div>`;
 }else if(s==='unverified'){
  const l=rec.loc;
  b.innerHTML=head('기록')+`<div class="rec-title warn a-up d1"><span class="bang">!</span><h2>위치 확인 안 됨</h2></div>
   <dl class="rec-dl a-up d2">${l.status==='none'?`<dt>이유</dt><dd>${esc(l.reason)}</dd>`:`<dt>정확도</dt><dd>±${l.acc} m <span class="muted">(기준 ${MAX_ACC} m)</span></dd><dt>구역</dt><dd>${l.dist<=MAX_DIST_KM?esc(l.zone.name):`관측 구역 밖 · ${l.dist.toFixed(1)} km`}</dd>`}</dl>
   <div class="two a-up d3"><button class="dark" data-rec="retry">다시 확인</button><button data-rec="saveonly">저장만 (집계 제외)</button></div>`;
 }else if(s==='level'){
  b.innerHTML=head('기록')+`<div class="rec-sub"><button class="back" data-rec="back" aria-label="뒤로">‹</button><b>나요</b><span class="muted">${chipText()} · ${rec.context==='outdoor'?'실외':'실내'}</span></div>
   <h2 class="a-up d1">얼마나 심해요?</h2>
   <div class="three big">${[[1,'약함'],[2,'보통'],[3,'심함']].map(([n,t],i)=>`<button class="a-pop d${i+2}" data-level="${n}"><b>${n}</b><span>${t}</span></button>`).join('')}</div>
   <span class="muted center a-up d5">누르면 바로 저장</span>`;
 }else if(s==='saving'){
  b.innerHTML=head('기록',false)+`<div class="rec-wait"><span class="spin"></span>저장 중</div>`;
 }else if(s==='error'){
  b.innerHTML=head('기록')+`<div class="rec-title warn a-up d1"><span class="bang">!</span><h2>저장 안 됨</h2></div><p class="a-up d2">${esc(rec.error)}</p><div class="two a-up d3"><button class="dark" data-rec="again">다시 시도</button><button data-rec="close">닫기</button></div>`;
 }else if(s==='done'){
  const r=rec.result;const what=r.odor===true?`나요 · 강도 ${r.intensity}`:r.odor===false?'안 나요':'모르겠어요';
  const n=nextScheduled();
  b.innerHTML=`<div class="rec-done"><svg class="check" viewBox="0 0 34 34" aria-hidden="true"><circle cx="17" cy="17" r="16" fill="#2E8B57"/><path d="M10 17.5l5 5 9-10" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="40"/></svg><h2>기록 완료</h2><span class="muted">#${esc((r.id||'').slice(0,4))}</span></div>
   <dl class="rec-dl a-up d3"><dt>내용</dt><dd>${esc(what)} · ${r.context==='outdoor'?'실외':'실내'}</dd><dt>위치</dt><dd>${esc(r.zone_name||'관측 구역 밖')} · ${r.check==='verified'?`확인됨 ±${rec.loc?.acc??'—'} m`:'미확인 · 집계 제외'}</dd><dt>구분</dt><dd>${r.mode==='scheduled'?'정기 관측':'수시 제보'}${r.odor===true&&r.check==='verified'?' · 지도에 표시':''}</dd></dl>
   <div class="two a-up d4"><button class="dark" data-rec="close">지도로</button><button data-rec="mine">내 기록</button></div>
   <span class="muted center a-up d5">다음 정기 관측 ${esc(n.label)} · 다음 기록 1분 뒤 가능</span>`;
 }
 b.querySelectorAll('[data-rec]').forEach(x=>x.onclick=()=>recAction(x.dataset.rec));
 b.querySelectorAll('[data-ctx]').forEach(x=>x.onclick=()=>{rec.context=x.dataset.ctx;renderRecord();});
 b.querySelectorAll('[data-level]').forEach(x=>x.onclick=()=>{rec.intensity=+x.dataset.level;save();});
}
function recAction(a){
 if(a==='close')closeRecord();
 else if(a==='retry')locate();
 else if(a==='saveonly'){rec.unverified=true;rec.step='ask';renderRecord();}
 else if(a==='yes'){rec.odor=true;rec.step='level';renderRecord();}
 else if(a==='no'){rec.odor=false;save();}
 else if(a==='unsure'){rec.odor=null;save();}
 else if(a==='back'){rec.step='ask';renderRecord();}
 else if(a==='again'){rec.step='ask';renderRecord();}
 else if(a==='mine'){closeRecord();setTab('part');}
}
function save(){
 rec.step='saving';renderRecord();
 const l=rec.loc||{};
 cmd('record_cmd',{odor:rec.odor,intensity:rec.odor===true?rec.intensity:null,context:rec.context,lat:l.lat??null,lon:l.lon??null,accuracy:l.acc??null,at:new Date().toISOString()});
}
function applyRecordResult(r){
 if(!rec||!r||r.cmd_id!==state?.record_cmd?.id||rec.step!=='saving'&&rec.step!=='done')return;
 if(rec.step==='done')return;
 if(!r.ok){rec.step='error';rec.error=r.error||'서버 연결 실패';renderRecord();return;}
 rec.result=r;rec.step='done';renderRecord();dropPin();
}
function dropPin(){
 const l=rec?.loc;if(!l||l.lat==null||!map||!window.L)return;
 if(recMarker)recMarker.remove();
 const n=rec.result?.odor===true?String(rec.result.intensity||''):'';
 recMarker=L.marker([l.lat,l.lon],{icon:L.divIcon({className:'rec-pin',html:`<i class="ring"></i><b>${esc(n)}</b>`,iconSize:[24,24],iconAnchor:[12,12]}),interactive:false,keyboard:false,zIndexOffset:950}).addTo(map);
}
// ------------------------------------------------------------------ 참여 · 계정 · 안내 · 기기 패널
const DAYS=['월','화','수','목','금','토','일'];
const panels={
 part(){
  const p=window.appArgs?.participation||{},w=p.week||{},days=w.days||[];
  const dots=days.map(d=>`<span><em>${esc(d.d)}</em>${d.future?'—':'●'.repeat(d.n)+'○'.repeat(Math.max(0,4-d.n))}</span>`).join('');
  const recent=(p.recent||[]).map(r=>`<div class="rec-item"><span class="muted">${esc(r.when)}</span><b>${esc(r.label)}</b><span class="tag">${r.mode==='scheduled'?'정기':'수시'}</span><span class="tag ${r.check==='verified'?'ok':'bad'}">${r.check==='verified'?'위치 ✓':'구역 밖'}</span></div>`).join('')||'<p class="muted">아직 기록이 없어요 · 아래 ＋ 기록</p>';
  const pct=w.total?Math.round(100*(w.done||0)/w.total):0;
  return {title:'참여',aside:`<button class="link-btn" data-open="account">계정 ›</button>`,content:`
   <div class="pcard"><div class="row"><span>이번 주 정기 관측</span><b>${w.done??0} <span class="muted">/ ${w.total??28}</span></b></div><div class="pbar"><i style="width:${pct}%"></i></div><div class="pdays">${dots}</div></div>
   <div class="pstats"><div><span>내 기록</span><b>${p.my_count??0}건</b></div><div><span>위치 확인</span><b>${p.verified_pct==null?'—':p.verified_pct+'%'}</b></div><div><span>이번 주 동네</span><b>${p.neighbors_week??0}명</b></div></div>
   <div class="row" style="margin-top:14px"><strong>내 기록</strong><span class="muted">최근</span></div><div class="rec-list">${recent}</div>
   <div class="menu" style="margin-top:12px"><button data-open="account"><span>정기 관측 알림<small>${acct.notify?'켬':'끔'} · 다음 ${esc(nextScheduled().label)}</small></span></button><button data-open="account"><span>참여 코드<small>${esc(acct.code||'')}${p.legacy_count?` · 예전 기록 ${p.legacy_count}건`:''}</small></span></button></div>`};
 },
 account(){
  const p=window.appArgs?.participation||{};
  const home=window.odorDevice?.homeZoneName?.();
  return {title:'계정',back:true,content:`
   <div class="acct"><span class="avatar">${esc((acct.nickname||'·').slice(-2))}</span><span class="who"><b>${esc(acct.nickname||'')}</b><span class="muted">${esc(acct.provider_name||'')}로 로그인${acct.email?` · ${esc(acct.email)}`:''}${acct.joined?` · ${esc(acct.joined.slice(5).replace('-','.'))} 가입`:''}</span></span><button class="link-btn" id="nick-edit">닉네임 변경</button></div>
   <form id="nick-form" class="search-row" hidden><input id="nick-in" class="field" maxlength="20" value="${esc(acct.nickname||'')}"><button type="submit">저장</button></form>
   <div class="menu">
    <button data-open="${window.odorDevice?.paired?'devhome':'pair'}"><span>우리 집<small>${esc(home||'기기 연결 후 설정')}</small></span></button>
    <button id="code-row"><span>참여 코드<small>${esc(acct.code||'')}${p.legacy_count?` · 예전 기록 ${p.legacy_count}건`:''}</small></span></button>
    <button id="notify-row"><span>정기 관측 알림<small>${acct.notify?'켬 · 앱을 열어 둔 동안 안내':'끔'}</small></span><i class="sw ${acct.notify?'on':''}"></i></button>
    <button id="replay-tut"><span>사용법 다시 보기<small>4장</small></span></button>
    <button id="logout" class="plain">로그아웃</button>
    <button id="withdraw" class="plain danger"><span>탈퇴<small>기록은 익명으로 남음</small></span></button>
   </div><p class="dev-msg" role="status" id="acct-msg">${esc(acct.notice||'')}</p>`};
 },
 help(){
  const dev=window.odorDevice,paired=dev?.paired;
  return {title:'안내',content:`<div class="menu">
   <button id="help-tut"><span>사용법<small>4장</small></span></button>
   <button data-open="devhome"><span>우리 집 기기<small>${paired?'공기청정기 1대':'연결된 기기 없음'}</small></span></button>
   <button data-open="info"><span>자료 정보<small>기상청 · 주민 관측</small></span></button>
   <button data-open="criteria">집계 기준</button><button data-open="flow">바람과 냄새</button><button data-open="privacy">위치 · 개인정보</button>
   <button data-open="account"><span>계정<small>${esc(acct.provider_name||'')} · ${esc(acct.nickname||'')}</small></span></button>
   ${acct.operator?'<button data-open="air">기기 USB 연결 (운영)</button>':''}
   </div><p class="muted" id="model-status">${esc(data?.model?.ok?(data.model.status||''):`추정 보류 · ${data?.model?.reason||''}`)}</p>`};
 },
 devhome(){
  const dev=window.odorDevice;
  if(!dev?.paired)return {title:'우리 집 기기',content:`<div class="dev-empty a-up d1"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.5 11L12 4l8.5 7v9h-17z" fill="none" stroke="#555" stroke-width="1.6" stroke-linejoin="round"/><circle cx="12" cy="14.5" r="2.2" fill="#555"/></svg><h3>연결된 기기 없음</h3><p>공기청정기를 연결하면 우리 집 구역에 냄새가 예보될 때 미리 가동합니다.</p><button class="primary-btn" data-open="pair">연결하기</button></div>`};
  const home=dev.homeZoneName?.();
  const eps=dev.info?.plan?.episodes||[];const now=Date.now();
  const rows=eps.slice(0,3).map(e=>`<div class="dev-ep"><span class="muted">${hm(e.on_at)}</span><b>${Date.parse(e.off_at)<now?'가동 끝':Date.parse(e.on_at)<=now?'가동 중':'가동 예정'}</b><span class="muted">${hm(e.odor_start)} ${esc(e.peak_level||'')} 예보 · ${hm(e.off_at)}까지</span></div>`).join('')||'<p class="muted">앞으로 가동 일정 없음</p>';
  return {title:'우리 집 기기',aside:`<span class="muted">${esc(home?home+' 예보로 자동':'구역 미정')}</span>`,content:`<div id="device-card"></div><div class="dev-eps">${rows}</div>`};
 }
};
function bindPanel(panel){
 const root=$('panel-content');
 if(panel==='account'){
  $('nick-edit').onclick=()=>{$('nick-form').hidden=!$('nick-form').hidden;$('nick-in').focus();};
  $('nick-form').onsubmit=e=>{e.preventDefault();const v=$('nick-in').value.trim();if(v.length<2)return;authCmd({op:'nickname',value:v});$('acct-msg').textContent='저장 중';};
  $('notify-row').onclick=()=>{authCmd({op:'notify',value:!acct.notify});};
  $('code-row').onclick=()=>{const c=prompt('예전에 쓰던 참여 코드(예: P01). 이 계정으로 기록을 이어 줍니다.','');if(c&&c.trim())authCmd({op:'link_code',code:c.trim().toUpperCase()});};
  $('replay-tut').onclick=replayTutorial;
  $('logout').onclick=()=>{stor.set(null);authCmd({op:'logout'});};
  $('withdraw').onclick=()=>{if(confirm('탈퇴하면 계정 정보는 지우고, 기록은 익명으로 남습니다. 진행할까요?')){stor.set(null);authCmd({op:'withdraw'});}};
 }else if(panel==='help'){$('help-tut').onclick=replayTutorial;}
 else if(panel==='devhome'){window.odorDevice?.renderCard();}
}
// ------------------------------------------------------------------ 상단 '기기' 버튼
function renderDevBtn(){
 const d=window.odorDevice?.summary?.();const dot=$('dev-dot');if(!dot)return;
 dot.hidden=!d;if(d)dot.className={solid:'g',outline:'b',warn:'r'}[d.pill]||'';
}
function bindShell(){
 $('dev-btn').onclick=()=>openPanel(window.odorDevice?.paired?'devhome':'devhome');
 $('rec-btn').onclick=openRecord;
 $('rec-dim').onclick=closeRecord;
 $('sched-chip').onclick=openRecord;
 setInterval(renderChip,30000);
}
document.addEventListener('DOMContentLoaded',()=>{bindAuth();bindShell();setEmailMode('login');});
window.odorApp={panels,bindPanel,applyAccount,applyRecordResult,renderChip,renderDevBtn,openRecord,get account(){return acct;},get record(){return rec;}};
})();
