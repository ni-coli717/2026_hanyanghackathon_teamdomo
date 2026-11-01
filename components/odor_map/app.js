'use strict';
// 코넥트 v4 · 지도 먼저(로그인 없이), 로그인은 ＋기록·참여·우리 집 기기를 열 때만 시트로. 사용법은 밝힌 곳을 눌러 넘기는 4단계.
// 서버와의 약속: 브라우저는 명령(auth_cmd / record_cmd)만 보내고, 판정·저장은 전부 Python 이 한다.
(function(){
const AUTH_KEY='odor.auth.v1';              // {refresh}: 이메일 로그인 유지용. 토큰 하나뿐, 키·비밀번호는 저장 안 함
const MAX_ACC=150,MAX_DIST_KM=1.5;          // core/geo_check 와 같은 값(표시용). 판정은 서버가 다시 한다
const SCHED=['07:30','12:30','18:30','22:00'];
const INTENT_KEY='odor.intent.v1';           // 로그인 전에 누른 기능(sessionStorage). OAuth 로 다녀와도 이어서 연다
const COACH_KEY='odor.coach.v1';             // 사용법을 봤거나 닫았음(localStorage)
let acct={status:'anon'},screen='',prev='',emailMode='login',pending=0,cmdSeq=0,tutSent=false,coachStep=-1;
let rec=null,recMarker=null,resumeTried=false;
const reduced=()=>window.matchMedia('(prefers-reduced-motion: reduce)').matches;
// 이메일 로그인 유지: localStorage + 같은 주소의 쿠키. 쿠키는 서버가 첫 실행에서 바로 읽어(st.context.cookies) '로그인 확인 중' 왕복을 줄인다.
const stor={get(){try{return JSON.parse(localStorage.getItem(AUTH_KEY)||'null');}catch(e){return null;}},
 set(v){try{if(v)localStorage.setItem(AUTH_KEY,JSON.stringify(v));else localStorage.removeItem(AUTH_KEY);}catch(e){}
  try{document.cookie='odor_refresh='+(v?encodeURIComponent(v.refresh):'')+'; path=/; max-age='+(v?2592000:0)+'; SameSite=Lax';}catch(e){}}};
const sess={get(){try{return sessionStorage.getItem(INTENT_KEY)||'';}catch(e){return '';}},set(v){try{if(v)sessionStorage.setItem(INTENT_KEY,v);else sessionStorage.removeItem(INTENT_KEY);}catch(e){}}};
const seen={get(){try{return localStorage.getItem(COACH_KEY)==='1';}catch(e){return false;}},set(){try{localStorage.setItem(COACH_KEY,'1');}catch(e){}}};
const isMember=()=>acct.status==='ok'||acct.status==='tutorial';
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
 if(name==='email'){$('em-mail').focus?.();}
}
function hideAuth(){$('auth').hidden=true;screen='';}
function msg(id,t){const el=$(id);if(el)el.textContent=t||'';}
function setBusy(on){document.querySelectorAll('#auth .primary-btn,#auth .auth-btn').forEach(b=>b.disabled=!!on);}
// ------------------------------------------------------------------ 계정 상태 반영
function applyAccount(a){
 const before=acct.status;
 acct=a||{status:'anon'};
 if(acct.refresh!==undefined){stor.set(acct.refresh?{refresh:acct.refresh}:null);}
 if(acct.cmd_done&&acct.cmd_done>=pending){pending=0;setBusy(false);}
 if(acct.status==='anon'){
  const saved=stor.get();
  // 이메일 로그인 유지: 화면을 막지 않고 뒤에서 조용히 복원한다
  if(saved?.refresh&&!resumeTried&&acct.providers?.email){resumeTried=true;authCmd({op:'resume',refresh:saved.refresh});}
  else if(!acct.providers?.email)stor.set(null);
  if(screen==='signup')hideAuth();
  if(screen==='email'){msg('email-msg',acct.notice||'');if(acct.notice)setBusy(false);}
  else if(rec?.step==='login'){renderLogin();if(acct.notice)msg('login-msg',acct.notice);}
 }else if(acct.status==='signup'){
  if(rec?.step==='login')closeRecord(true);
  if(screen!=='signup'&&screen!=='doc'){showScreen('signup');$('signup-via').textContent=acct.provider_name?`${acct.provider_name} 계정`:'';if(acct.name&&!$('su-nick').value)$('su-nick').value=acct.name.slice(0,20);}
  msg('signup-msg',acct.notice||'');
 }else{
  // 가입 직후(tutorial)도 회원. 사용법은 지도 위 4단계라 서버 표시만 끝낸다.
  if(acct.status==='tutorial'&&!tutSent){tutSent=true;setTimeout(()=>authCmd({op:'tutorial_done'}),0);}
  if(screen==='email'||screen==='signup')hideAuth();
  if(rec?.step==='login')closeRecord(true);
  const intent=sess.get();
  if(intent){sess.set('');setTimeout(()=>runIntent(intent),0);}
 }
 if(before!==acct.status||acct.notice)setTimeout(()=>window.odorMap?.render(),0);
}
// 로그인이 필요한 기능: 회원이면 바로, 아니면 하려던 일을 기억하고 로그인 시트
function requireLogin(intent){
 if(isMember()){runIntent(intent);return;}
 sess.set(intent);openLogin(intent);
}
function runIntent(intent){
 if(!isMember()||!window.odorMap?.map)return;
 if(intent==='record')openRecord();
 else if(intent==='device')openPanel('devhome');
 else if(intent==='part')setTab('part');
 else if(intent==='account')setTab('account');
}
const LOGIN_COPY={
 record:['기록은 로그인 후에 남길 수 있어요','누가 언제 기록했는지 알아야 정기 관측으로 셉니다'],
 device:['우리 집 기기는 로그인 후에 연결해요','기기와 계정을 이어야 우리 집 구역 예보로 가동합니다'],
 part:['참여 기록은 로그인 후에 볼 수 있어요','내 기록과 이번 주 정기 관측을 모아 봅니다'],
 account:['로그인','처음이면 닉네임만 정하면 됩니다'],
};
function loginButtons(prefix){
 const p=acct.providers||{},none=!p.kakao&&!p.google&&!p.email;
 return `<div class="login-btns">${p.kakao?`<button class="auth-btn kakao" data-login="kakao"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4C6.9 4 3 7.1 3 11c0 2.4 1.6 4.6 4 5.8L6.3 20l3.8-2.4c.6.1 1.3.2 1.9.2 5.1 0 9-3.1 9-7s-3.9-6.8-9-6.8z" fill="#191919"/></svg>카카오로 시작</button>`:''}${p.google?'<button class="auth-btn google" data-login="google"><span class="g">G</span>구글로 시작</button>':''}${p.email?'<button class="auth-btn grey" data-login="email">이메일로 시작</button>':''}</div><p id="${prefix}-msg" class="auth-msg" role="status">${none?'로그인 준비 중 · 운영자가 설정하면 열립니다':''}</p>`;
}
function bindLoginButtons(root,msgId){
 root.querySelectorAll('[data-login]').forEach(b=>b.onclick=()=>{
  const pv=b.dataset.login;
  if(pv==='email'){if(rec?.step==='login')closeRecord(true);msg('email-msg','');showScreen('email');return;}
  msg(msgId,pv==='kakao'?'카카오로 이동 중':'구글로 이동 중');root.querySelectorAll('[data-login]').forEach(x=>x.disabled=true);
  authCmd({op:'login',provider:pv});
 });
 root.querySelectorAll('[data-doc]').forEach(b=>b.onclick=()=>openDoc(b.dataset.doc));
}
function openLogin(intent){
 rec={step:'login',intent};
 $('rec-dim').hidden=false;$('rec').hidden=false;$('rec').classList.remove('out');
 renderLogin();
}
function renderLogin(){
 if(rec?.step!=='login')return;
 const [h,sub]=LOGIN_COPY[rec.intent]||LOGIN_COPY.account;
 const b=$('rec-body');
 b.innerHTML=`<div class="rec-head"><strong>로그인</strong><button class="x" data-rec="close" aria-label="닫기">✕</button></div>
  <h2 class="login-h a-up d1">${esc(h)}</h2><p class="login-sub a-up d2">${esc(sub)}</p>${loginButtons('login')}
  <p class="login-foot">로그인 없이도 지도와 예보는 그대로 볼 수 있어요</p><div class="auth-links"><button data-doc="terms">이용약관</button><button data-doc="privacy">개인정보 처리방침</button></div>`;
 b.querySelector('[data-rec=close]').onclick=()=>{sess.set('');closeRecord();};
 bindLoginButtons(b,'login-msg');
}
// ------------------------------------------------------------------ 로그인 · 가입
function bindAuth(){
 document.querySelectorAll('[data-back]').forEach(b=>b.onclick=()=>{const t=b.dataset.back==='prev'?prev:'';if(t)showScreen(t,'back');else{hideAuth();sess.set('');}});
 document.querySelectorAll('#auth [data-doc]').forEach(b=>b.onclick=()=>openDoc(b.dataset.doc));
 $('signup-later').onclick=()=>{sess.set('');stor.set(null);authCmd({op:'logout'});hideAuth();};
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
}
function setEmailMode(m){emailMode=m;document.querySelectorAll('.tabs2 [role=tab]').forEach(t=>t.setAttribute('aria-selected',String(t.dataset.mode===m)));document.querySelector('.tabs2 .thumb').style.transform=m==='login'?'translateX(0)':'translateX(100%)';$('email-go').textContent=m==='login'?'로그인':'다음';$('em-pw').autocomplete=m==='login'?'current-password':'new-password';}
const DOCS={
 terms:['이용약관','<p>코넥트는 김포 운양동 주민이 냄새를 기록하고 예보를 보는 참여형 서비스입니다.</p><p>기록은 연구·예보 개선과 지역 공유 자료로 쓰이며, 개인을 알 수 있는 형태로 공개하지 않습니다.</p><p>허위 기록·반복 기록은 집계에서 제외될 수 있습니다. 서비스는 예고 없이 바뀌거나 중단될 수 있습니다.</p>'],
 privacy:['개인정보 처리방침','<p><b>수집 항목</b> 로그인 계정 식별자, 이메일(가린 형태로 표시), 닉네임, 기록할 때의 위치(약 100 m 단위로 반올림), 기록 내용.</p><p><b>이용 목적</b> 기록 저장과 본인 확인, 구역 판정, 예보 계산.</p><p><b>보관</b> 계정 삭제를 요청하면 계정 정보는 지우고 기록은 익명으로 남습니다.</p><p><b>제3자</b> 우리 집 검색은 OpenStreetMap 에 검색어만 보냅니다. 그 밖에 외부로 보내지 않습니다.</p>'],
};
function openDoc(k){const d=DOCS[k];if(!d)return;$('doc-title').textContent=d[0];$('doc-body').innerHTML=d[1];if(!screen)prev='';showScreen('doc');}
// ------------------------------------------------------------------ 사용법: 지도 위 4단계 · 밝힌 곳을 눌러야 다음
const COACH=[
 {sel:'#head',h:'색 = 냄새 날 가능성',s:'이 구역 오늘 가능성이에요 · 카드를 눌러 앞으로 6시간 보기'},
 {sel:'#tabs [data-tab=forecast]',h:'예보와 지난 기록',s:'앞으로 몇 시간 · 지난 관측도 여기서 · 예보를 눌러 보세요'},
 {sel:'#wind-btn',h:'바람이 가는 쪽',s:'지도 위 작은 화살표도 같은 뜻이에요 · 바람 버튼을 눌러 보세요'},
 {sel:'#rec-btn',h:'냄새 나면 ＋기록',s:'두 번 누르면 끝 · 처음 한 번만 로그인해요'},
];
function startCoach(){
 if(!window.odorMap?.map)return;
 hideAuth();if(rec)closeRecord(true);
 window.odorMap.expand(false);
 coachStep=0;$('coach').hidden=false;$('coach-chip').hidden=true;
 showCoach();
}
function coachTarget(){return coachStep<0?null:document.querySelector(COACH[coachStep].sel);}
function showCoach(){
 if(coachStep<0)return;
 const c=COACH[coachStep],t=coachTarget();
 $('coach-num').textContent=`사용법 ${coachStep+1} / ${COACH.length}`;$('coach-h').textContent=c.h;$('coach-s').textContent=c.s;
 $('coach-dots').innerHTML=COACH.map((_,i)=>`<span class="${i===coachStep?'on':''}"></span>`).join('');
 placeCoach(t);setTimeout(()=>placeCoach(coachTarget()),380);   // 시트가 펴지는 동안 위치가 바뀐다
}
function placeCoach(t){
 if(coachStep<0||!t)return;
 const r=t.getBoundingClientRect(),pad=6,hole=$('coach-hole'),tip=$('coach-tip');
 Object.assign(hole.style,{left:`${r.left-pad}px`,top:`${r.top-pad}px`,width:`${r.width+pad*2}px`,height:`${r.height+pad*2}px`,borderRadius:t.id==='rec-btn'?'40px':'16px'});
 const below=r.top+r.height/2<window.innerHeight/2;
 tip.style.top=below?`${r.bottom+pad+12}px`:'';tip.style.bottom=below?'':`${window.innerHeight-r.top+pad+12}px`;
}
function coachNext(from){
 if(coachStep!==from)return;
 if(coachStep>=COACH.length-1){endCoach();return;}
 coachStep++;showCoach();
}
function endCoach(skip){
 coachStep=-1;$('coach').hidden=true;seen.set();renderCoachChip();
 if(skip)window.odorMap?.expand(false);
}
// 사용법 중에는 밝힌 곳과 안내 카드만 눌린다
function coachGuard(e){
 if(coachStep<0)return;
 const el=e.target;if($('coach-tip').contains(el))return;
 const t=coachTarget();
 if(t&&t.contains(el)){if(e.type==='click'){const n=coachStep;setTimeout(()=>coachNext(n),0);}return;}
 e.stopPropagation();if(e.cancelable)e.preventDefault();
}
function renderCoachChip(){const el=$('coach-chip');if(el)el.hidden=seen.get()||coachStep>=0||$('shell').hidden;}
// ------------------------------------------------------------------ 정기 관측 칩
function nextScheduled(){
 const now=new Date();const p=parts(now.toISOString());const cur=Number(p.hour)*60+Number(p.minute);
 for(const s of SCHED){const [h,m]=s.split(':').map(Number);const t=h*60+m;if(t+15>=cur)return {label:s,minutes:t-cur};}
 const [h,m]=SCHED[0].split(':').map(Number);return {label:SCHED[0],minutes:h*60+m+1440-cur};
}
function renderChip(){
 const el=$('sched-chip');if(!el||!data)return;
 renderCoachChip();
 const n=nextScheduled();el.hidden=false;el.querySelector('b').textContent=n.label;
 const live=n.minutes<=15;el.classList.toggle('live',live);
 el.childNodes[1].textContent=live?'정기 관측 중 ':'다음 정기 관측 ';
}
// ------------------------------------------------------------------ ＋ 기록
function openRecord(){
 if(!isMember()){requireLogin('record');return;}
 rec={step:'locate',loc:null,context:'outdoor',odor:null,intensity:null,unverified:false,error:''};
 $('rec-dim').hidden=false;$('rec').hidden=false;$('rec').classList.remove('out');
 renderRecord();locate();
}
function closeRecord(now){
 if(!rec)return;
 const r=rec,done=()=>{if(rec!==r)return;$('rec').hidden=true;$('rec-dim').hidden=true;rec=null;};
 if(now||reduced()){done();return;}
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
  b.innerHTML=`<div class="rec-done"><svg class="check" viewBox="0 0 34 34" aria-hidden="true"><circle cx="17" cy="17" r="16" fill="#1F7A4B"/><path d="M10 17.5l5 5 9-10" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="40"/></svg><h2>기록 완료</h2><span class="muted">#${esc((r.id||'').slice(0,4))}</span></div>
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
// ------------------------------------------------------------------ 참여 · 계정(안내 포함) · 기기 패널
const DAYS=['월','화','수','목','금','토','일'];
const panels={
 part(){
  const p=window.appArgs?.participation||{},w=p.week||{},days=w.days||[];
  const dots=days.map(d=>`<span><em>${esc(d.d)}</em>${d.future?'—':'●'.repeat(d.n)+'○'.repeat(Math.max(0,4-d.n))}</span>`).join('');
  const recent=(p.recent||[]).map(r=>`<div class="rec-item"><span class="muted">${esc(r.when)}</span><b>${esc(r.label)}</b><span class="tag">${r.mode==='scheduled'?'정기':'수시'}</span><span class="tag ${r.check==='verified'?'ok':'bad'}">${r.check==='verified'?'위치 ✓':'구역 밖'}</span></div>`).join('')||'<p class="muted">아직 기록이 없어요 · 아래 ＋ 기록</p>';
  const pct=w.total?Math.round(100*(w.done||0)/w.total):0;
  return {title:'참여',content:`
   <div class="pcard"><div class="row"><span>이번 주 정기 관측</span><b>${w.done??0} <span class="muted">/ ${w.total??28}</span></b></div><div class="pbar"><i style="width:${pct}%"></i></div><div class="pdays">${dots}</div></div>
   <div class="pstats"><div><span>내 기록</span><b>${p.my_count??0}건</b></div><div><span>위치 확인</span><b>${p.verified_pct==null?'—':p.verified_pct+'%'}</b></div><div><span>이번 주 동네</span><b>${p.neighbors_week??0}명</b></div></div>
   <div class="row" style="margin-top:14px"><strong>내 기록</strong><span class="muted">최근</span></div><div class="rec-list">${recent}</div>
   <div class="menu" style="margin-top:12px"><button data-goto="account"><span>정기 관측 알림<small>${acct.notify?'켬':'끔'} · 다음 ${esc(nextScheduled().label)}</small></span></button><button data-goto="account"><span>참여 코드<small>${esc(acct.code||'')}${p.legacy_count?` · 예전 기록 ${p.legacy_count}건`:''}</small></span></button></div>`};
 },
 account(){
  const guide=`<h3 class="menu-h">안내</h3><div class="menu">
   <button id="replay-tut"><span>사용법 다시 보기<small>지도 위 4단계</small></span></button>
   <button data-open="info"><span>자료 정보<small>기상청 · 주민 관측</small></span></button>
   <button data-open="zones">구역 기준</button><button data-open="criteria">집계 기준</button><button data-open="flow">바람과 냄새</button><button data-open="privacy">위치 · 개인정보</button>
   <button data-doc="terms">이용약관</button>
   ${acct.operator?'<button data-open="air">기기 USB 연결 (운영)</button>':''}
   </div><p class="muted" id="model-status">${esc(data?.model?.ok?(data.model.status||''):`추정 보류 · ${data?.model?.reason||''}`)}</p>`;
  if(!isMember())return {title:'계정',content:`
   <div class="acard a-up d1"><b>로그인하면</b><span>냄새 기록 · 우리 집 기기 · 내 참여 기록</span><small>지도와 예보는 로그인 없이 그대로</small></div>
   ${loginButtons('acct-login')}${guide}`};
  const p=window.appArgs?.participation||{};
  const dev=window.odorDevice,home=dev?.homeZoneName?.();
  return {title:'계정',content:`
   <div class="acct"><span class="avatar">${esc((acct.nickname||'·').slice(-2))}</span><span class="who"><b>${esc(acct.nickname||'')}</b><span class="muted">${esc(acct.provider_name||'')}로 로그인${acct.email?` · ${esc(acct.email)}`:''}${acct.joined?` · ${esc(acct.joined.slice(5).replace('-','.'))} 가입`:''}</span></span><button class="link-btn" id="nick-edit">닉네임 변경</button></div>
   <form id="nick-form" class="search-row" hidden><input id="nick-in" class="field" maxlength="20" value="${esc(acct.nickname||'')}"><button type="submit">저장</button></form>
   <div class="menu">
    <button data-open="devhome"><span>우리 집 기기<small>${dev?.paired?`공기청정기 1대${home?` · ${esc(home)}`:''}`:'연결된 기기 없음'}</small></span></button>
    <button id="notify-row"><span>정기 관측 알림<small>${acct.notify?'켬 · 앱을 열어 둔 동안 안내':'끔'}</small></span><i class="sw ${acct.notify?'on':''}"></i></button>
    <button id="code-row"><span>참여 코드<small>${esc(acct.code||'')}${p.legacy_count?` · 예전 기록 ${p.legacy_count}건`:''}</small></span></button>
   </div>
   ${guide}
   <div class="menu"><button id="logout" class="plain">로그아웃</button><button id="withdraw" class="plain danger"><span>탈퇴<small>기록은 익명으로 남음</small></span></button></div>
   <p class="dev-msg" role="status" id="acct-msg">${esc(acct.notice||'')}</p>`};
 },
 devhome(){
  const dev=window.odorDevice;
  if(!dev?.paired)return {title:'우리 집 기기',content:`<div class="dev-empty a-up d1"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.5 11L12 4l8.5 7v9h-17z" fill="none" stroke="#52636C" stroke-width="1.6" stroke-linejoin="round"/><circle cx="12" cy="14.5" r="2.2" fill="#52636C"/></svg><h3>연결된 기기 없음</h3><p>공기청정기를 연결하면 우리 집 구역에 냄새가 예보될 때 미리 가동합니다.</p><button class="primary-btn" data-open="pair">연결하기</button></div>`};
  const home=dev.homeZoneName?.();
  const eps=dev.info?.plan?.episodes||[];const now=Date.now();
  const rows=eps.slice(0,3).map(e=>`<div class="dev-ep"><span class="muted">${hm(e.on_at)}</span><b>${Date.parse(e.off_at)<now?'가동 끝':Date.parse(e.on_at)<=now?'가동 중':'가동 예정'}</b><span class="muted">${hm(e.odor_start)} ${esc(e.peak_level||'')} 예보 · ${hm(e.off_at)}까지</span></div>`).join('')||'<p class="muted">앞으로 가동 일정 없음</p>';
  return {title:'우리 집 기기',aside:`<span class="muted">${esc(home?home+' 예보로 자동':'구역 미정')}</span>`,content:`<div id="device-card"></div><div class="dev-eps">${rows}</div>`};
 }
};
function bindPanel(panel){
 const root=$('panel-content');
 if(panel==='account'){
  $('replay-tut').onclick=startCoach;
  root.querySelectorAll('[data-doc]').forEach(b=>b.onclick=()=>openDoc(b.dataset.doc));
  if(!isMember()){bindLoginButtons(root,'acct-login-msg');return;}
  $('nick-edit').onclick=()=>{$('nick-form').hidden=!$('nick-form').hidden;$('nick-in').focus();};
  $('nick-form').onsubmit=e=>{e.preventDefault();const v=$('nick-in').value.trim();if(v.length<2)return;authCmd({op:'nickname',value:v});$('acct-msg').textContent='저장 중';};
  $('notify-row').onclick=()=>{authCmd({op:'notify',value:!acct.notify});};
  $('code-row').onclick=()=>{const c=prompt('예전에 쓰던 참여 코드(예: P01). 이 계정으로 기록을 이어 줍니다.','');if(c&&c.trim())authCmd({op:'link_code',code:c.trim().toUpperCase()});};
  $('logout').onclick=()=>{stor.set(null);sess.set('');authCmd({op:'logout'});};
  $('withdraw').onclick=()=>{if(confirm('탈퇴하면 계정 정보는 지우고, 기록은 익명으로 남습니다. 진행할까요?')){stor.set(null);sess.set('');authCmd({op:'withdraw'});}};
 }else if(panel==='part'){root.querySelectorAll('[data-goto]').forEach(b=>b.onclick=()=>setTab(b.dataset.goto));}
 else if(panel==='devhome'){window.odorDevice?.renderCard();}
}
// ------------------------------------------------------------------ 상단 '기기' 버튼
function renderDevBtn(){
 const d=window.odorDevice?.summary?.();const dot=$('dev-dot');if(!dot)return;
 dot.hidden=!d;if(d)dot.className={solid:'g',outline:'b',warn:'r'}[d.pill]||'';
}
function bindShell(){
 $('dev-btn').onclick=()=>openPanel('devhome');   // 로그인 전이면 map.js 관문이 로그인 시트를 연다
 $('rec-btn').onclick=openRecord;
 $('rec-dim').onclick=()=>{if(rec?.step==='login')sess.set('');closeRecord();};
 $('sched-chip').onclick=openRecord;
 $('coach-start').onclick=startCoach;
 $('coach-dismiss').onclick=()=>{seen.set();renderCoachChip();};
 $('coach-skip').onclick=()=>endCoach(true);
 ['click','pointerdown','mousedown','touchstart','wheel'].forEach(t=>window.addEventListener(t,coachGuard,{capture:true,passive:false}));
 window.addEventListener('resize',()=>placeCoach(coachTarget()));
 setInterval(renderChip,30000);
}
document.addEventListener('DOMContentLoaded',()=>{bindAuth();bindShell();setEmailMode('login');});
window.odorApp={panels,bindPanel,applyAccount,applyRecordResult,renderChip,renderDevBtn,openRecord,requireLogin,startCoach,get member(){return isMember();},get coachStep(){return coachStep;},get account(){return acct;},get record(){return rec;}};
})();
