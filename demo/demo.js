'use strict';
// 코넥트 시연 웹 · 진행 담당.
// 화면은 실제 앱(components/odor_map)을 그대로 띄우고, Streamlit 서버가 하던 일(자료 보내기·기록 응답)만 여기서 대신한다.
// 자료는 demo/data.js (python -m demo.build_data · 그날 관측값을 실제 모델로 다시 계산한 값). 여기서 숫자를 지어내지 않는다.
//
// 진행 방식
// - 위쪽 띠: 흐름 지도(입력 → 처리 → 출력, 다시 학습). 지금 장면 칸이 강조된다.
// - 안내 카드: 눌러야 할 곳 옆에 뜬다. 움직이는 동안은 '보고 있는 것'을 말하고, 끝나면 다음에 누를 곳을 가리킨다.
// - 장면 안의 움직임만 자동으로 흐르고, 다음 장면은 반드시 클릭(카드 단추 또는 → 키)으로만 넘어간다.
(function(){
const D=window.DEMO,$=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const T=hm=>Date.parse(`${D.day}T${hm}:00+09:00`);
const iso=ms=>new Date(ms+9*3600000).toISOString().slice(0,19)+'+09:00';
const hhmm=ms=>iso(ms).slice(11,16);
const LEVEL_CLASS={'낮음':'low','보통':'mid','높음':'high'};
const zones=D.payload.zones,zoneOf=id=>zones.find(z=>z.id===id),home=zoneOf(D.home_zone);
const frameAt=h=>D.payload.frames.find(f=>f.at.slice(0,13)===`${D.day}T${h}`);
const levelAt=(h,z)=>frameAt(h)?.zones?.[z]?.pred?.level||null;
const reduced=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
// 배포본(Streamlit 컴포넌트 · ?demo=1) 안에서 도는지. 그 안에서는 USB(Web Serial)를 브라우저가 막고, 지도 저장(sw.js)은 쓰지 않는다.
const EMBED=/\/component\//.test(location.pathname);
// 배포본: Streamlit 에 '준비됨'만 알린다(보내는 값 없음). 안 알리면 Streamlit 이 컴포넌트 시간 초과 경고를 띄운다.
if(EMBED)try{window.parent.postMessage({isStreamlitMessage:true,apiVersion:1,type:'streamlit:componentReady'},'*');}catch(e){}
const wait=ms=>new Promise(r=>setTimeout(r,ms));

// ------------------------------------------------------------------ 속도 (S 설정 · 기본 '느리게')
const SPEEDS={slow:1,normal:.7,fast:.45};
let speedKey='slow';try{speedKey=localStorage.getItem('konect.demo.speed')||'slow';}catch(e){}
if(!SPEEDS[speedKey])speedKey='slow';
const dur=ms=>reduced()?Math.min(ms,200):ms*SPEEDS[speedKey];

// ------------------------------------------------------------------ 그날 자료에서 읽어 내는 이야기
const [Y,M,DD]=D.day.split('-').map(Number);
const HOURS=['15','16','17','18','19','20','21','22','23'];
const peakH=HOURS.find(h=>levelAt(h,D.home_zone)==='높음')||HOURS.at(-1);
const midH=HOURS.find(h=>levelAt(h,D.home_zone)==='보통'&&+h<+peakH);
const ep=D.episodes[0]||null,onAt=ep?Date.parse(ep.on_at):null,offAt=ep?Date.parse(ep.off_at):null,odorAt=ep?Date.parse(ep.odor_start):null;
const leadMin=ep?Math.round((odorAt-onAt)/60000):0;
const mine=D.mine!=null?D.reports[D.mine]:null,mineAt=mine?Date.parse(mine.at):T('21:00');
const nReports=D.reports.reduce((a,r)=>a+r.n,0),nZones=new Set(D.reports.map(r=>r.zone)).size;
const LEVEL_WORD={1:'약함',2:'보통',3:'심함'};
// '19시까지 낮음 → 20시 보통 → 21시 높음' (우리 집 구역, 15시부터 첫 높음까지)
function riseText(){
 const hs=HOURS.slice(0,HOURS.indexOf(peakH)+1),out=[];
 hs.forEach(h=>{const l=levelAt(h,D.home_zone)||'보류';if(out.length&&out.at(-1).l===l)out.at(-1).to=h;else out.push({l,from:h,to:h});});
 return out.map((g,k)=>k<out.length-1&&g.from!==g.to?`${+g.to}시까지 ${g.l}`:`${+g.from}시 ${g.l}`).join(' → ');
}
const lv=(word)=>`<span class="lv-${LEVEL_CLASS[word]||'hold'}">${esc(word||'보류')}</span>`;

// ------------------------------------------------------------------ 상태
let i=0,now=T('15:00'),ready=false,position=D.record_point.slice(),mode='auto',manualUntil=null;
let recorded=false,lastRecord=null,lastCmd=0,fanOn=null,pushedKey='',shownCounts={},runId=0,started=false;
const frame=$('app'),W=()=>frame.contentWindow,doc=()=>{try{return W().document;}catch(e){return null;}};
const CANCEL=Symbol('cancel');
const alive=id=>{if(id!==runId)throw CANCEL;};
const pause=async(ms,id)=>{await wait(dur(ms));alive(id);};

// ------------------------------------------------------------------ 실제 앱에 보내는 자료 (서버가 보내던 것과 같은 모양)
// 발표자가 ＋기록으로 대신하는 제보(D.mine)는, 발표자가 기록했거나 그 장면을 지난 뒤에만 센다.
function reportsSoFar(){return D.reports.filter((r,k)=>Date.parse(r.at)<=now&&(k!==D.mine||recorded||i>3));}
function recent(){
 const out={};
 reportsSoFar().filter(r=>now-Date.parse(r.at)<=3*3600000).forEach(r=>{(out[r.zone]=out[r.zone]||{count:0,device:0}).count+=r.n;});
 return out;
}
function push(){
 if(!ready)return;
 const floor=Math.floor((now+9*3600000)/3600000)*3600000-9*3600000;
 const frames=D.payload.frames.filter(f=>Date.parse(f.at)>=floor);
 const payload={...D.payload,frames,latest_index:0,now:iso(now),outlook:D.outlook[hhmm(now).slice(0,2)]||{}};
 const rc=recent();
 const args={payload,selection:{position,at:frames[0].at,sequence:9e15},initial_state:{tab:'forecast',collapsed:false},
  account:{status:'ok',provider:'demo',provider_name:'시연',nickname:'시연',code:'DEMO',email:'',joined:'',notify:false,operator:false,providers:{}},
  device:null,participation:null,record:lastRecord,recent:rc,device_api:{url:'https://demo.invalid',key:'demo',zone_map:D.zone_map}};
 W().__demo?.setNow(now);
 W().postMessage({type:'streamlit:render',args},'*');
 W().odorDevice?.refresh();
 pushedKey=keyNow();
 syncFan();
 // 구역 이름표의 '제보 N' 이 오른 구역은 잠깐 강조한다(점은 찍지 않는다: 다른 주민의 실제 좌표는 쓰지 않음).
 const up=Object.keys(rc).filter(z=>rc[z].count>(shownCounts[z]||0));shownCounts=Object.fromEntries(Object.entries(rc).map(([z,v])=>[z,v.count]));
 if(up.length)setTimeout(()=>bump(up),80);
}
// 시계가 흐를 때 다시 보낼지: 시(時)가 바뀌었거나, 보이는 제보가 바뀌었거나, 팬 상태가 바뀌었을 때만
const keyNow=()=>`${hhmm(now).slice(0,2)}|${reportsSoFar().length}|${fanShouldRun()}`;
function bump(zoneIds){
 const d=doc();if(!d)return;
 zoneIds.forEach(id=>{const z=zoneOf(id);const el=[...d.querySelectorAll('.zone-label')].find(x=>x.querySelector('b')?.textContent===z?.name);
  const t=el?.querySelector('i');if(!t)return;t.classList.remove('demo-bump');void t.offsetWidth;t.classList.add('demo-bump');});
}
// 기기 서버 응답(device_get): 15:00 에 계산한 그날 일정
function fanShouldRun(){
 if(mode==='on')return true;if(mode==='off')return false;
 return D.episodes.some(e=>Date.parse(e.on_at)<=now&&now<Date.parse(e.off_at));
}
function deviceInfo(){
 return {now:iso(now),source:mode==='auto'?'plan':'manual',
  settings:{mode,name:'우리 집 공기청정기',zone_id:D.zone_map[D.home_zone],trigger_level:'높음',lead_min:40,tail_min:30,manual_until:manualUntil},
  status:{seen_at:iso(now-20000),fan:fanShouldRun()},
  plan:{state:'ok',computed_at:iso(Math.floor(now/900000)*900000),basis:'demo',episodes:D.episodes}};
}
window.DEMO_HOST={
 now:()=>now,position:()=>D.record_point.slice(),   // 시연 속 주민 위치: 우리 집 구역 면 안쪽(build_data 가 경계에서 가장 먼 점으로 고름)
 storage:()=>({'odor.device.v1':JSON.stringify({id:'AP01',token:'demo',home:{label:'우리 집',lat:home.lat,lon:home.lon,zone:home.id}})}),
 deviceRpc(name,body){
  if(name==='device_set'&&body.p_mode){mode=body.p_mode;manualUntil=mode==='auto'?null:iso(now+2*3600000);setTimeout(syncFan,0);}
  return name==='device_get'?deviceInfo():null;
 },
 key:e=>key(e),
};
let onSaved=null;
window.addEventListener('message',e=>{
 if(e.source!==W()||!e.data?.isStreamlitMessage)return;
 if(e.data.type==='streamlit:componentReady'){ready=true;injectStyle();push();if(!started){started=true;setTimeout(()=>go(0),300);}}
 if(e.data.type==='streamlit:setComponentValue'){
  const v=e.data.value||{};
  if(Array.isArray(v.position))position=v.position;
  if(v.record_cmd&&v.record_cmd.id!==lastCmd){lastCmd=v.record_cmd.id;setTimeout(()=>saved(v.record_cmd),600);}
 }
});
// 실제 앱에서는 이 자리에서 서버가 위치를 다시 판정하고 DB에 저장한다. 시연은 저장하지 않고 같은 모양의 응답만 돌려준다.
function saved(c){
 let z=null,best=Infinity;
 if(c.lat!=null)zones.forEach(x=>{const d=Math.hypot(x.lat-c.lat,(x.lon-c.lon)*Math.cos(c.lat*Math.PI/180));if(d<best){best=d;z=x;}});
 lastRecord={cmd_id:c.id,ok:true,id:'demo'+String(c.id).slice(-4),odor:c.odor,intensity:c.intensity,context:c.context,zone_name:z?.name||'',check:z?'verified':'unverified',mode:'spontaneous'};
 if(c.odor===true)recorded=true;
 push();
 const f=onSaved;onSaved=null;f&&f(c);
}

// ------------------------------------------------------------------ 시계
function setClock(){$('clock').textContent=hhmm(now);updateTimeline();drawBig();}
// 시계가 흐르는 동안 지도 가운데에 큰 시계(바늘이 돈다). 끝나면 위쪽 띠 시계로 돌아간다.
function drawBig(){
 const b=$('bigclock');if(!b||b.hidden)return;
 const [h,m]=hhmm(now).split(':').map(Number);
 $('bc-time').textContent=hhmm(now);
 $('bc-min').setAttribute('transform',`rotate(${m*6} 32 32)`);$('bc-hour').setAttribute('transform',`rotate(${(h%12)*30+m*.5} 32 32)`);
}
function showBig(on){
 const b=$('bigclock');
 if(on){b.hidden=false;b.classList.remove('out');drawBig();return;}
 if(b.hidden)return;b.classList.add('out');
 const c=$('clock');c.classList.remove('land');void c.offsetWidth;c.classList.add('land');
 setTimeout(()=>{if(b.classList.contains('out'))b.hidden=true;},260);
}
// 시계를 to 까지 흘린다(ease-in-out). 시(時)·제보·팬 상태가 바뀌면 앱에 다시 보낸다. 장면이 바뀌면 그 자리에서 멈춘다.
function tween(to,ms,id){
 return new Promise(res=>{
  const from=now;ms=dur(ms);
  if(from===to||ms<=1){now=to;setClock();if(keyNow()!==pushedKey)push();res();return;}
  const t0=performance.now();
  const tick=t=>{if(id!==runId){res();return;}
   const p=Math.min(1,(t-t0)/ms),e=p<.5?2*p*p:1-Math.pow(-2*p+2,2)/2;
   now=p<1?Math.round((from+(to-from)*e)/60000)*60000:to;setClock();if(keyNow()!==pushedKey)push();
   if(p<1)requestAnimationFrame(tick);else res();};
  requestAnimationFrame(tick);
 });
}
// 시계를 흘리되(큰 시계), 그사이 들어온 제보마다 1.5초 멈춰서 이름표의 숫자가 오르는 걸 보여 준다. 흐르는 시간은 합쳐서 약 3초.
async function flowTo(to,id,onStop){
 showBig(true);
 try{await flowSteps(to,id,onStop);}finally{showBig(false);}
}
async function flowSteps(to,id,onStop){
 const stops=[...new Set(D.reports.map((r,k)=>({t:Date.parse(r.at),k})).filter(s=>s.t>now&&s.t<=to&&s.k!==D.mine).map(s=>s.t))];
 const span=Math.max(1,to-now);
 for(const t of [...stops,to]){
  await tween(t,Math.max(400,3000*(t-now)/span),id);alive(id);
  if(t!==to){onStop&&onStop(t);await pause(1600,id);}
 }
}

// ------------------------------------------------------------------ 앱 화면 위 맥박 표시 · 누름 기다리기
function injectStyle(){
 const d=doc();if(!d||d.getElementById('demo-style'))return;
 const st=d.createElement('style');st.id='demo-style';
 // 맥박: 항상 보이는 2px 테두리 + 퍼지는 고리. ＋기록(주황) 위에서도 보이게 테두리는 진한 청록, 고리는 흰 틈을 둔다.
 st.textContent=`@keyframes demoPulse{0%{box-shadow:0 0 0 2px #fff,0 0 0 4px rgba(10,106,133,.9)}100%{box-shadow:0 0 0 2px #fff,0 0 0 18px rgba(10,106,133,0)}}
 .demo-hint{animation:demoPulse 1.4s cubic-bezier(.23,1,.32,1) infinite;outline:2px solid #0A6A85;outline-offset:3px;cursor:pointer;position:relative;z-index:2}
 .tl-controls.demo-hint{border-radius:12px}
 @keyframes demoBump{0%{transform:scale(1);background:rgba(255,255,255,0)}25%{transform:scale(1.2);background:#fff;box-shadow:0 0 0 3px rgba(10,106,133,.35)}100%{transform:scale(1);background:rgba(255,255,255,0);box-shadow:0 0 0 10px rgba(10,106,133,0)}}
 .zone-label i.demo-bump{display:inline-block;border-radius:6px;padding:0 4px;animation:demoBump .9s cubic-bezier(.23,1,.32,1) both}
 @media (prefers-reduced-motion:reduce){.demo-hint{animation:none}.zone-label i.demo-bump{animation:none;background:#fff}}
 /* 시연에 쓰지 않는 앱 요소는 숨긴다(앱 코드는 그대로): 탭은 예보 · ＋기록만, 정기 관측 칩, 머리의 시각, 지도 단추 일부, 작은 설명 줄 */
 #tabs [data-tab=now],#tabs [data-tab=part],#tabs [data-tab=help],#sched-chip,#header-at,#locate,#pick,#zoom-in,#zoom-out{display:none!important}
 #panel-content .timeline>.row:last-child,#time-mode,#panel-content>p.muted,#panel-aside{display:none!important}
 #rec-body .rec-chip>.muted,#rec-body .muted.center{display:none!important}
 #rec-body .rec-done~.rec-dl dt:nth-of-type(3),#rec-body .rec-done~.rec-dl dd:nth-of-type(3){display:none!important}
 #device-card .dev-foot,.dev-eps{display:none!important}
 /* 둥글기 줄이기 */
 #device-card,.zones button{border-radius:8px!important}
 /* 공기청정기 가동 중: 카드가 청록으로 바뀌고, 표시 안의 팬이 돈다 */
 #device-card{transition:background-color .3s ease,border-color .3s ease}
 #device-card:has(.pill.solid){border-color:#0A6A85;background:#EEF7FA}
 #device-card .pill.solid{display:inline-flex;align-items:center;gap:5px;border-radius:6px}
 #device-card .pill.solid::before{content:"";width:13px;height:13px;background:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cg fill='%23fff'%3E%3Cellipse cx='12' cy='6.2' rx='3.4' ry='5.6'/%3E%3Cellipse cx='12' cy='6.2' rx='3.4' ry='5.6' transform='rotate(120 12 12)'/%3E%3Cellipse cx='12' cy='6.2' rx='3.4' ry='5.6' transform='rotate(240 12 12)'/%3E%3C/g%3E%3C/svg%3E") center/contain no-repeat;animation:demoSpin .9s linear infinite}
 @keyframes demoSpin{to{transform:rotate(360deg)}}
 @media (prefers-reduced-motion:reduce){#device-card .pill.solid::before{animation:none}}`;
 d.head.appendChild(st);
}
// 앱은 그릴 때마다 패널 내용을 새로 만든다. 그래서 요소에 직접 붙이지 않고 선택자로 기억해 두었다가
// 다시 그려질 때마다 표시를 다시 얹고(MutationObserver), 누르는 건 문서에서 먼저 받는다(pointerdown, 캡처 단계).
let hintSel=null,hintCb=null,hintIntercept=false,hintWatch=false,swallow=0;
function applyHint(){
 const d=doc();if(!d)return;
 d.querySelectorAll('.demo-hint').forEach(x=>{if(!hintSel||!x.matches(hintSel))x.classList.remove('demo-hint');});
 if(hintSel){const el=d.querySelector(hintSel);if(el&&!el.classList.contains('demo-hint'))el.classList.add('demo-hint');}
}
function watchHints(){
 const d=doc();if(!d||hintWatch)return;hintWatch=true;
 let raf=0;new MutationObserver(()=>{if(!raf)raf=requestAnimationFrame(()=>{raf=0;applyHint();});}).observe(d.body,{childList:true,subtree:true});
 d.addEventListener('pointerdown',e=>{
  if(!hintSel)return;const t=e.target.closest?.(hintSel);if(!t||t.disabled)return;
  const cb=hintCb,stop=hintIntercept;hint(null);
  if(stop){e.preventDefault();e.stopPropagation();swallow=performance.now();}
  cb&&cb();
 },true);
 // 가로챈 누름의 뒤따르는 mousedown/click 은 앱에 넘기지 않는다(시간 막대가 누른 자리로 튀지 않게)
 ['mousedown','click'].forEach(t=>d.addEventListener(t,e=>{if(swallow&&performance.now()-swallow<600){e.preventDefault();e.stopPropagation();if(t==='click')swallow=0;}},true));
}
function hint(sel,cb,intercept=false){
 hintSel=sel||null;hintCb=cb||null;hintIntercept=!!intercept;
 try{injectStyle();watchHints();applyHint();}catch(e){}
}
// 앱 화면의 sel 을 누를 때까지 기다린다. intercept=true 면 그 누름은 앱에 넘기지 않는다.
function tapApp(sel,id,intercept){return new Promise(res=>hint(sel,()=>res(),intercept)).then(()=>alive(id));}
async function appEl(sel,id,ok=el=>true){for(;;){const el=doc()?.querySelector(sel);if(el&&ok(el))return el;await wait(120);alive(id);}}
function closeRecord(){try{const d=doc()?.getElementById('rec-dim');if(d&&!d.hidden)d.click();}catch(e){}}
function app(name,...a){try{return W()[name]?.(...a);}catch(e){}}
function appState(){try{return W().odorMap?.state||null;}catch(e){return null;}}
function appTab(panel){
 const st=appState();if(!st)return;
 if(st.tab!=='forecast')app('setTab','forecast');
 if((appState()?.panel||'')!==(panel||''))app('openPanel',panel||'');
}

// ------------------------------------------------------------------ 흐름 지도 (위쪽 띠)
const NODE_OF=['forecast','model','device','record','sensor','model'];
function updateFlow(){
 const cur=NODE_OF[i],seen=new Set(NODE_OF.slice(0,i));if(i>=1)seen.add('map');
 document.querySelectorAll('#flow [data-node]').forEach(n=>{const k=n.dataset.node;n.className=k===cur?'cur':seen.has(k)?'seen':'';});
}
function learnFlow(){const f=$('flow');f.classList.remove('learn');void f.offsetWidth;f.classList.add('learn');}

// ------------------------------------------------------------------ 안내 카드
// o = {where, step, big, small, act:{text}|{lead, button, onClick}, target:{app:sel}|{el}, side:'below'|'right'|'left'}
let card=null,cardTimer=null,cardFn=null;
function showCard(o){
 const el=$('card');card=o;cardFn=o.act?.onClick||null;
 $('c-where').textContent=o.where||'';$('c-step').textContent=o.step||'';
 $('c-big').innerHTML=o.big||'';$('c-small').innerHTML=o.small||'';$('c-small').hidden=!o.small;
 const a=$('c-act');a.hidden=!o.act;a.className='c-act'+(o.act?.button?' has-btn':'');
 if(o.act?.button)a.innerHTML=`<button type="button" class="go">${esc(o.act.button)} ▸</button>`;
 else if(o.act?.text)a.innerHTML=`<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8.5" fill="none" stroke="#0A6A85" stroke-width="1.5" opacity=".4"/><circle cx="10" cy="10" r="4.5" fill="#0A6A85"/></svg>${esc(o.act.text)}`;
 else if(o.act?.watch)a.innerHTML=`<span class="watch">${esc(o.act.watch)}</span>`;
 const b=a.querySelector('button');if(b)b.onclick=()=>{const f=cardFn;cardFn=null;f&&f();};
 const body=$('c-body');body.classList.remove('swap');void body.offsetWidth;body.classList.add('swap');
 if(el.hidden){el.hidden=false;el.classList.remove('in');void el.offsetWidth;el.classList.add('in');placeCard(true);}else placeCard(false);
 clearInterval(cardTimer);cardTimer=setInterval(()=>placeCard(false),200);
}
function hideCard(){clearInterval(cardTimer);card=null;cardFn=null;$('card').hidden=true;}
function targetRect(t){
 if(!t)return null;let r=null;
 if(t.app){const e=doc()?.querySelector(t.app);if(e){const b=e.getBoundingClientRect();if(b.width||b.height)r={left:b.left,top:b.top,right:b.right,bottom:b.bottom};}}
 else if(t.el){const e=typeof t.el==='string'?$(t.el):t.el;if(e&&!e.hidden){const b=e.getBoundingClientRect(),s=$('stage').getBoundingClientRect();r={left:b.left-s.left,top:b.top-s.top,right:b.right-s.left,bottom:b.bottom-s.top};}}
 return r;
}
function placeCard(first){
 if(!card)return;const el=$('card'),st=$('stage');
 const Wd=st.clientWidth,Hd=st.clientHeight,cw=el.offsetWidth,ch=el.offsetHeight,G=16,r=targetRect(card.target);
 let x=G,y=G,side=r?card.side||'below':'none',tail=0;
 if(r){
  const ar=card.anchor?targetRect({el:document.querySelector(card.anchor)}):null;
  const cx=ar?(ar.left+ar.right)/2:(r.left+r.right)/2,cy=(r.top+r.bottom)/2;
  if(side==='below'){x=cx-56;y=r.bottom+18;if(y+ch>Hd-G){side='above';y=r.top-18-ch;}}
  if(side==='above'){x=cx-56;y=r.top-18-ch;}
  if(side==='right'){x=r.right+18;y=card.dy!=null?r.top+card.dy:cy-ch/2;}
  if(side==='left'){x=r.left-18-cw;y=card.dy!=null?r.top+card.dy:cy-ch/2;}
  x=Math.max(G,Math.min(Wd-cw-G,x));y=Math.max(G,Math.min(Hd-ch-G,y));
  tail=side==='below'||side==='above'?Math.max(22,Math.min(cw-22,cx-x)):Math.max(22,Math.min(ch-22,cy-y));
 }
 el.dataset.side=side;el.style.setProperty('--tail',tail+'px');
 el.classList.toggle('moving',!first);
 el.style.transform=`translate(${Math.round(x)}px,${Math.round(y)}px)`;
}
window.addEventListener('resize',()=>placeCard(true));

// ------------------------------------------------------------------ 시간선 (기기 장면)
const FAN='<svg class="fan" viewBox="0 0 24 24" aria-hidden="true"><g fill="currentColor"><ellipse cx="12" cy="6.2" rx="3.4" ry="5.6"/><ellipse cx="12" cy="6.2" rx="3.4" ry="5.6" transform="rotate(120 12 12)"/><ellipse cx="12" cy="6.2" rx="3.4" ry="5.6" transform="rotate(240 12 12)"/></g><circle cx="12" cy="12" r="2" fill="#fff"/></svg>';
const TL_FROM=T('15:00'),TL_TO=T('23:00'),tlPct=ms=>Math.max(0,Math.min(100,(ms-TL_FROM)/(TL_TO-TL_FROM)*100));
function buildTimeline(){
 if(!ep)return;
 const pt=(ms,cls,label,where)=>`<span class="pt ${cls}" style="left:${tlPct(ms)}%"></span><span class="lb ${where} ${cls}" data-at="${ms}" style="left:${tlPct(ms)}%">${label}</span>`;
 $('timeline').innerHTML=`<div class="tl"><span class="axis"></span><span class="band" style="left:${tlPct(onAt)}%;width:${tlPct(offAt)-tlPct(onAt)}%"></span>
  ${pt(onAt,'on',`<b>${hhmm(onAt)}</b><span>${FAN}공기청정기 가동</span>`,'below')}
  ${pt(odorAt,'odor',`<b>${hhmm(odorAt)}</b> 높음 예보`,'above')}
  ${pt(offAt,'off',`<b>${hhmm(offAt)}</b><span>종료</span>`,'below')}
  <span class="pt now" id="tl-now"></span><span class="lb below nowlb" id="tl-nowlb"><b></b><span>지금</span></span>
  <span class="lead" style="left:${tlPct(onAt)}%;width:${tlPct(odorAt)-tlPct(onAt)}%">${leadMin}분 먼저</span></div>`;
}
function updateTimeline(){
 const t=$('timeline');if(!t||t.hidden||!ep)return;
 const p=tlPct(now);$('tl-now').style.left=p+'%';const nl=$('tl-nowlb');nl.style.left=p+'%';nl.querySelector('b').textContent=hhmm(now);
 const near=Math.abs(p-tlPct(onAt))<6||Math.abs(p-tlPct(offAt))<6;nl.classList.toggle('hide',near);
 t.querySelector('.lb.on').classList.toggle('lit',now>=onAt&&now<offAt);t.querySelector('.pt.on').classList.toggle('lit',now>=onAt&&now<offAt);
 const run=now>=onAt&&now<offAt;
 if(run&&!t.classList.contains('running')){t.classList.remove('kick');void t.offsetWidth;t.classList.add('kick');}   // 켜지는 순간 한 번 번쩍
 t.classList.toggle('running',run);
}
function showTimeline(on,intro){const t=$('timeline');t.hidden=!on||!ep;t.classList.remove('running','kick','intro');if(on){if(intro){void t.offsetWidth;t.classList.add('intro');}updateTimeline();}}

// ------------------------------------------------------------------ 장면
const SCENES=[
 {name:'기상 예보',t:'15:00',run:sceneForecast},
 {name:'모델 판단',t:'15:00',run:sceneModel},
 {name:'공기청정기 예약',t:'15:00',run:sceneDevice},
 {name:'주민 기록',t:hhmm(mineAt),run:sceneRecord},
 {name:'센서 측정',t:hhmm(mineAt+5*60000),run:sceneSensor},
 {name:'다시 학습',t:'22:40',run:sceneLoop},
];
function go(n){
 n=Math.max(0,Math.min(SCENES.length-1,n));
 const id=++runId;
 if(n===0){recorded=false;lastRecord=null;mode='auto';manualUntil=null;shownCounts={};position=D.record_point.slice();}
 i=n;const s=SCENES[i];
 $('scene-name').textContent=s.name;$('count').textContent=`${i+1} / ${SCENES.length}`;
 stopOver();closeRecord();hint(null);hideCard();showTimeline(false);showBig(false);$('bigclock').hidden=true;updateFlow();$('flow').classList.remove('learn');
 s.run(id).catch(e=>{if(e!==CANCEL)console.error(e);});
}
const next=()=>go(i+1);

// 장면 1 · 예보 탭의 시간 막대를 15시부터 첫 높음까지 한 칸씩(앱의 setTime 을 그대로 부른다)
// 카드 문구 규칙: 문장으로 끝내지 않는다 · 제목 위 이름표 없음 · 단추 옆 유도 문장 없음 · 작은 줄은 제목에 없는 새 정보 하나만
async function sceneForecast(id){
 await tween(T('15:00'),600,id);alive(id);push();appTab('');app('setTime',0);
 showCard({step:'1 / 2',big:`${Y}.${M}.${DD} 하루 재현`,small:'시연용으로 고른 실제 하루',
  act:{text:'슬라이드바 눌러 시간 확인'},target:{app:'.tl-controls'},side:'right'});
 await pause(300,id);await tapApp('.tl-controls',id,true);
 const frames=D.payload.frames.filter(f=>Date.parse(f.at)>=T('15:00'));
 const last=frames.findIndex(f=>f.at.slice(11,13)===peakH);
 let prev=null;
 for(let k=0;k<=last;k++){
  const h=frames[k].at.slice(11,13),l=levelAt(h,D.home_zone);app('setTime',k);
  showCard({step:'2 / 2',big:`${+h}시 · ${lv(l)}`,small:`${esc(home.name)}`,target:{app:'.tl-controls'},side:'right'});
  await pause(1500+(prev&&l!==prev?2000:0),id);prev=l;
 }
 showCard({step:'2 / 2',big:esc(riseText()).replace(/(낮음|보통|높음)/g,m=>lv(m)),
  act:{button:'모델 판단 과정 보기',onClick:next},target:{app:'.tl-controls'},side:'right'});
}

// 장면 2 · 모델 판: 시각마다 ① 바람 → ② 기여도 한 줄씩 → ③ 점수 바늘 → ④ 단계 낱말
async function sceneModel(id){
 showOver('model');
 await tween(T('15:00'),600,id);alive(id);push();appTab('');
 const hours=[...new Set(['15',midH,peakH].filter(Boolean))];
 for(const [k,h] of hours.entries()){
  showCard({step:`${k+1} / ${hours.length}`,big:`${+h}시`,small:'바람 → 기여도 → 점수 → 단계',target:{el:'over'},side:'left',dy:24});
  await modelHour(h,id);
  const x=D.explain.find(e=>e.zone===D.home_zone&&e.at.slice(0,13)===`${D.day}T${h}`),g=Object.entries(x.groups).sort((a,b)=>b[1]-a[1]);
  const up=g.filter(v=>v[1]>0.05),down=g.filter(v=>v[1]<-0.05).reverse();
  const why=[up[0]&&`↑ ${up[0][0]} +${up[0][1].toFixed(2)}`,down[0]&&`↓ ${down[0][0]} −${Math.abs(down[0][1]).toFixed(2)}`].filter(Boolean).join(' · ');
  showCard({step:`${k+1} / ${hours.length}`,big:`${+h}시 · ${lv(levelAt(h,D.home_zone))}`,small:`점수 ${x.score.toFixed(2)}${why?' · '+why:''}`,target:{el:'over'},side:'left',dy:24});
  await pause(k<hours.length-1?2600:900,id);
 }
 showCard({big:'풍향·풍속·습도로<br>시간별 냄새 가능성 예측',
  act:{button:'공기청정기 일정',onClick:next},target:{el:'over'},side:'left',dy:24});
}

// 장면 3 · 공기청정기 예약: 시간선이 먼저 뜨고, 카드는 시간선을 가리킨다. [20:20으로]를 누르면 큰 시계가 흐르고, 20:20 에 켜진다.
async function sceneDevice(id){
 await tween(T('15:00'),600,id);alive(id);push();appTab('devhome');
 if(!ep){showCard({big:'높음 예보 없음 · 가동 일정 없음',act:{button:'주민 기록',onClick:next},target:{app:'#device-card'},side:'right'});return;}
 buildTimeline();showTimeline(true,true);
 await appEl('#device-card',id,e=>e.offsetHeight>40);
 await pause(1200,id);
 const at={target:{el:'timeline'},anchor:'#timeline .pt.on',side:'above'};
 await new Promise(res=>showCard({step:'1 / 2',big:`냄새 ${leadMin}분 전 가동 예약`,small:`${+peakH}시 높음 → ${hhmm(onAt)} 가동`,
  act:{button:`${hhmm(onAt)}으로`,onClick:res},...at}));
 alive(id);
 hideCard();
 await flowTo(onAt,id);
 showCard({step:'2 / 2',big:`${hhmm(onAt)} 공기청정기 가동`,small:`${hhmm(offAt)} 종료`,
  act:{button:'주민 기록',onClick:next},...at});
}

// 장면 4 · 주민 기록: 다른 주민 기록이 들어오고(큰 시계) → ＋기록 → 나요 → 강도 → 저장 뒤 '다시 학습'
async function sceneRecord(id){
 appTab('');
 if(now<mineAt){
  showCard({big:'주민 기록 수신',target:{app:'#rec-btn'},side:'below'});
  await pause(900,id);
  await flowTo(mineAt,id);
 }else{await tween(mineAt,600,id);alive(id);}
 push();appTab('');
 if(recorded){afterRecordCard(id);return;}
 lastRecord=null;
 showCard({step:'1 / 3',big:'냄새 나면 주민이 직접 기록',small:'두 번 클릭',act:{text:'＋기록 클릭'},target:{app:'#rec-btn'},side:'below'});
 await pause(400,id);await tapApp('#rec-btn',id,false);
 await appEl('[data-rec="yes"]',id,e=>!e.disabled);
 showCard({step:'2 / 3',big:'‘나요’ 클릭',target:{app:'[data-rec="yes"]'},side:'left'});
 const savedP=new Promise(res=>{onSaved=res;});
 await Promise.race([tapApp('[data-rec="yes"]',id,false),savedP]);
 if(!recorded&&!lastRecord){
  const lvSel=mine?.intensity?`[data-level="${mine.intensity}"]`:'[data-level="3"]';
  await appEl('[data-level]',id);
  showCard({step:'3 / 3',big:`‘${LEVEL_WORD[mine?.intensity]||'강도'}’ 클릭`,small:mine?.intensity?`그날 이 시각 ${esc(home.name)} 기록: 강도 ${mine.intensity}`:'',
   target:{app:lvSel},side:'left'});
  hint(lvSel);
 }
 await savedP;alive(id);hint(null);
 showCard({big:'기록 완료',small:'시연: DB 저장 안 함',target:{app:'#rec-btn'},side:'below'});
 await pause(2200,id);closeRecord();await pause(500,id);
 afterRecordCard(id);
}
function afterRecordCard(id){
 learnFlow();
 showCard({big:'기록 → 다시 학습',small:`그날 저녁 ${nZones}개 구역 · ${nReports}건`,
  act:{button:'외부 센서 측정값 확인',onClick:next},target:{app:'#rec-btn'},side:'below'});
}

// 장면 5 · 센서: 세 줄(예보 · 주민 · 센서)이 차례로
async function sceneSensor(id){
 if(EMBED&&!practice&&!ports.sensor){$('practice').checked=true;startPractice();}
 showOver('sensor');
 showCard({big:'예보 · 주민 기록 · 센서 비교',target:{el:'over'},side:'left',dy:24});
 await tween(T(SCENES[4].t),600,id);alive(id);push();appTab('');refreshAgree();
 for(const row of document.querySelectorAll('#over .agree > div')){await pause(1300,id);row.classList.add('in');}
 await pause(600,id);
 showCard({big:'예보 · 주민 기록 · 센서 비교',small:practice?'센서: <b>연습용 가상 신호</b>':ports.sensor?'센서: 기준(처음 5초 평균) 대비 변화':'센서 연결 전',
  act:{button:'다시 학습',onClick:next},target:{el:'over'},side:'left',dy:24});
}

// 장면 6 · 다시 학습: 4단계가 차례로(단계당 0.8초)
async function sceneLoop(id){
 showOver('loop');learnFlow();
 const big='실시간 주민 관측 기록 수집을<br>통한 모델 향상';
 showCard({big,target:{el:'over'},side:'left',dy:24});
 await tween(T('22:40'),600,id);alive(id);push();appTab('');
 await pause(4*800+400,id);
 showCard({big,act:{button:'처음부터',onClick:()=>go(0)},target:{el:'over'},side:'left',dy:24});
}

function key(e){
 const k=e.key;
 if(k==='ArrowRight'||k==='PageDown'){if(cardFn){const f=cardFn;cardFn=null;f();}else next();return true;}
 if(k==='ArrowLeft'||k==='PageUp'){go(i-1);return true;}
 if(new RegExp(`^[1-${SCENES.length}]$`).test(k)&&!e.ctrlKey&&!e.metaKey&&!e.altKey){go(+k-1);return true;}
 if(k==='s'||k==='S'||k==='ㄴ'){$('setup').hidden=!$('setup').hidden;return true;}
 return false;
}
document.addEventListener('keydown',e=>{if(key(e))e.preventDefault();});

// ------------------------------------------------------------------ 설명 판
let overTimer=null,overKind='';
function stopOver(){clearInterval(overTimer);overTimer=null;overKind='';$('over').hidden=true;$('over').innerHTML='';}
function showOver(kind){
 const el=$('over');overKind=kind;el.hidden=false;el.style.animation='none';void el.offsetWidth;el.style.animation='';
 ({model:overModel,sensor:overSensor,loop:overLoop})[kind](el);
}
// 장면 2 · 모델이 본 것
const DIR16=['북','북북동','북동','동북동','동','동남동','남동','남남동','남','남남서','남서','서남서','서','서북서','북서','북북서'];
const SHORT=n=>n.replace(/^(고양|김포)\s*/,'').replace(/\(.*\)/,'').replace(/\s*(축산지역|주변)$/,'');
let modelDraw=null;
function overModel(el){
 let zone=D.home_zone,angle=null;
 const th=D.thresholds,lo=.30,hi=.85,pct=v=>`${Math.max(0,Math.min(100,(v-lo)/(hi-lo)*100))}%`;
 el.innerHTML=`<div class="top"><div>
   <div class="verdict"><span class="word" id="m-word"></span><span class="when" id="m-when"></span></div></div>
   <div class="seg" role="group" aria-label="구역">${zones.map(z=>`<button data-z="${z.id}">${esc(z.name)}</button>`).join('')}</div></div>
  <div class="rule"></div>
  <div class="model">
   <div class="compass"><svg viewBox="-62 6 374 238" role="img" aria-label="풍향과 발생원 후보의 방향">
     <circle cx="125" cy="125" r="88" fill="none" stroke="#DCE5E9" stroke-width="1.5"/>
     <text x="125" y="27" text-anchor="middle" font-size="17" fill="#5E6C74">북</text>
     <g id="m-src"></g>
     <g class="wind" id="m-wind"><g class="streaks" fill="none" stroke="#0A6A85" stroke-width="2.5" stroke-linecap="round"><path d="M109 46V100"/><path d="M125 40V104"/><path d="M141 46V100"/></g><path d="M115 96l10 10 10-10" fill="none" stroke="#0A6A85" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></g>
     <text id="m-windtxt" x="-56" y="232" font-size="17" font-weight="700" fill="#0A6A85"></text>
     <circle cx="125" cy="125" r="5" fill="#0A6A85"/><text id="m-zone" x="125" y="150" text-anchor="middle" font-size="17" font-weight="700" fill="#12222B"></text>
    </svg>
   </div>
   <div class="why"><h2>요인별 기여도</h2><div id="m-contrib"></div>
    <div class="score"><div class="row"><span>점수 · 평소 0.50</span><b id="m-score">—</b></div>
     <div class="ticks"><span style="left:${pct(th.mid)}">보통 ${th.mid.toFixed(2)}</span><span style="left:${pct(th.high)}">높음 ${th.high.toFixed(2)}</span></div>
     <div class="scale-wrap"><div class="scale"><i class="lo" style="width:${pct(th.mid)}"></i><i class="mi" style="width:calc(${pct(th.high)} - ${pct(th.mid)})"></i><i class="hi" style="flex:1"></i></div><span class="needle" id="m-needle" style="left:${pct(.5)}"></span></div></div>
   </div>
  </div>
  <div class="rule"></div>
  <div class="hours" id="m-hours"></div>`;
 // phase: 0 바람만 · 1~n 막대 n줄 · 'needle' · 'all'
 modelDraw=(hour,phase)=>{
  const x=D.explain.find(e=>e.zone===zone&&e.at.slice(0,13)===`${D.day}T${hour}`),l=levelAt(hour,zone),cls=LEVEL_CLASS[l]||'hold';
  const groups=Object.entries(x.groups),nBars=phase==='needle'||phase==='all'?groups.length:typeof phase==='number'?phase:0;
  const word=$('m-word');
  if(phase==='all'){word.textContent=l||'보류';word.className='word show lv-'+cls;}else{word.className='word';}
  $('m-when').textContent=`${+hour}시 · ${zoneOf(zone).name}`;
  el.querySelectorAll('[data-z]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.z===zone)));
  $('m-zone').textContent=zoneOf(zone).name;
  $('m-src').innerHTML=D.bearings.filter(b=>b.zone===zone).map(b=>{const r=b.bearing*Math.PI/180,px=125+88*Math.sin(r),py=125-88*Math.cos(r),tx=125+100*Math.sin(r),ty=125-100*Math.cos(r)+6;
   return `<circle cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="4.5" fill="${b.type==='축산계'?'#5E6C74':'#fff'}" stroke="#5E6C74" stroke-width="1.5"/><text x="${tx.toFixed(1)}" y="${ty.toFixed(1)}" text-anchor="${Math.sin(r)>.25?'start':Math.sin(r)<-.25?'end':'middle'}" font-size="16" fill="#52636C">${esc(SHORT(b.name))}</text>`;}).join('');
  angle=angle===null?x.wind_from:angle+((((x.wind_from-angle)%360)+540)%360-180);$('m-wind').style.transform=`rotate(${angle}deg)`;
  const calm=x.wind_speed<(D.payload.calm_ms??.5);$('m-wind').style.opacity=calm?.3:1;
  $('m-windtxt').textContent=calm?`바람 약함 ${(+x.wind_speed).toFixed(1)} m/s`:`바람 ${DIR16[Math.round(((x.wind_from%360)+360)%360/22.5)%16]}풍 ${(+x.wind_speed).toFixed(1)} m/s`;
  const box=$('m-contrib');
  if(!box.children.length)box.innerHTML=groups.map(([g])=>`<div class="contrib"><span>${esc(g)}</span><span class="track"><span class="fill" data-g="${esc(g)}"></span></span><span class="v" data-v="${esc(g)}"></span></div>`).join('');
  groups.forEach(([g,v],k)=>{const f=box.querySelector(`[data-g="${g}"]`),on=k<nBars,w=on?Math.min(50,Math.abs(v)/2*50):0;
   f.className='fill '+(v>=0?'pos':'neg');f.style.left=v>=0?'50%':`${50-w}%`;f.style.width=`${w}%`;
   const t=box.querySelector(`[data-v="${g}"]`);t.textContent=on?(v>=0?'+':'−')+Math.abs(v).toFixed(2):'';});
  const showScore=phase==='needle'||phase==='all';
  $('m-score').textContent=showScore?x.score.toFixed(2):'—';$('m-needle').style.left=pct(showScore?x.score:.5);
  $('m-hours').innerHTML=HOURS.map(h=>{const hl=levelAt(h,zone),c=LEVEL_CLASS[hl]||'hold';return `<button data-h="${h}" aria-pressed="${h===hour}"><span class="t">${+h}시</span><span class="slot"><span class="bar ${c}"></span></span><span class="l lv-${c}">${esc(hl||'—')}</span></button>`;}).join('');
  el.querySelectorAll('[data-h]').forEach(b=>b.onclick=()=>{curHour=b.dataset.h;modelDraw(curHour,'all');});
 };
 el.querySelectorAll('[data-z]').forEach(b=>b.onclick=()=>{zone=b.dataset.z;modelDraw(curHour,'all');});
 curHour='15';modelDraw('15',0);
}
let curHour='15';
async function modelHour(h,id){
 curHour=h;const n=Object.keys(D.explain[0].groups).length;
 modelDraw(h,0);await pause(1000,id);                       // ① 바람
 for(let k=1;k<=n;k++){modelDraw(h,k);await pause(450,id);} // ② 한 줄씩
 modelDraw(h,'needle');await pause(1100,id);                 // ③ 점수 바늘
 modelDraw(h,'all');await pause(700,id);                     // ④ 단계 낱말
}
// 장면 5 · 센서 실측
// 표본은 {t,v}. 기준 = 받기 시작한 뒤 처음 5초 동안의 평균. 5초 넘게 새 값이 없거나 포트가 끊기면 '센서 끊김'.
const samples=[],WINDOW=160,BASE_MS=5000,STALE_MS=5000;let sensorLabel='',practice=null,t0=null,base=null,lost=false,lastAt=0;
function resetSamples(){samples.length=0;t0=null;base=null;lost=false;lastAt=0;}
function addSample(v){
 const t=performance.now();if(t0===null)t0=t;lastAt=t;lost=false;
 samples.push({t,v});if(samples.length>WINDOW)samples.shift();
 if(base===null&&t-t0>=BASE_MS){const first=samples.filter(s=>s.t-t0<=BASE_MS);base=first.reduce((a,s)=>a+s.v,0)/first.length;}
 if(overKind==='sensor')drawSensor();
}
function sensorLost(){if(lost)return;lost=true;$('sensor-state').textContent='끊김';if(overKind==='sensor')drawSensor();}
setInterval(()=>{if(ports.sensor&&!practice&&lastAt&&performance.now()-lastAt>STALE_MS)sensorLost();},1000);
function overSensor(el){
 const l=levelAt(peakH,D.home_zone);
 el.innerHTML=`<h1>실시간 센서 측정값</h1><div class="rule"></div>
  <div class="sensor"><div class="chart"><span class="tag" id="s-tag"></span><svg viewBox="0 0 1000 400" preserveAspectRatio="none" aria-hidden="true"><line id="s-base" x1="0" x2="1000" stroke="#5E6C74" stroke-width="1.5" stroke-dasharray="6 6" vector-effect="non-scaling-stroke" visibility="hidden"/><polyline id="s-line" fill="none" stroke="#0A6A85" stroke-width="3" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/></svg><span class="base-tag" id="s-base-tag" hidden>기준(처음 5초 평균)</span><div class="empty" id="s-empty">센서 연결 전</div></div>
   <dl class="agree"><div><dt>예보 · ${+peakH}시 ${esc(home.name)}</dt><dd class="lv-${LEVEL_CLASS[l]||'hold'}">${esc(l||'보류')}</dd></div>
    <div><dt>주민 기록 · 오늘 저녁</dt><dd id="s-rep"></dd></div>
    <div><dt>센서 · 지금</dt><dd id="s-now">—<small>연결 전</small></dd></div></dl></div>`;
 refreshAgree();drawSensor();
}
function refreshAgree(){const r=reportsSoFar(),e=$('s-rep');if(e)e.innerHTML=`${r.reduce((a,x)=>a+x.n,0)}건<small>${new Set(r.map(x=>x.zone)).size}개 구역</small>`;}
function drawSensor(){
 const line=$('s-line');if(!line)return;
 const has=samples.length>1;
 $('s-empty').hidden=has;
 $('s-tag').textContent=!has?'':lost?'센서 끊김':practice?'연습용 가상 신호':sensorLabel||'센서 값';
 $('s-tag').className='tag'+(lost?' lost':practice?' virt':'');
 line.setAttribute('stroke-dasharray',practice?'7 6':'');line.style.opacity=lost?.3:1;
 if(!has)return;
 const vs=samples.map(s=>s.v),ref=base??vs[0];
 const min=Math.min(...vs,ref*.95),max=Math.max(...vs,ref*1.3),pad=(max-min||1)*.08,y=v=>380-(v-min+pad)/(max-min+2*pad)*360;
 // 가로는 늘 그래프 전체 폭(모인 표본 수에 맞춰 늘인다)
 line.setAttribute('points',vs.map((v,k)=>`${(k/(vs.length-1)*1000).toFixed(1)},${y(v).toFixed(1)}`).join(' '));
 const bl=$('s-base'),bt=$('s-base-tag');
 if(base!==null){const yb=y(base).toFixed(1);bl.setAttribute('y1',yb);bl.setAttribute('y2',yb);bl.setAttribute('visibility','visible');bt.hidden=false;bt.style.top=`calc(${(yb/400*100).toFixed(2)}% + 6px)`;}
 else{bl.setAttribute('visibility','hidden');bt.hidden=true;}
 const virt=practice?'<em class="virt">연습용 가상</em>':'';
 if(lost){$('s-now').innerHTML='센서 끊김<small>마지막 값 숨김</small>';$('s-now').className='lost';return;}
 $('s-now').className='';
 if(base===null){$('s-now').innerHTML=`기준 재는 중${virt}<small>처음 5초 평균</small>`;return;}
 const cur=vs.at(-1),d=Math.round((cur-base)/base*100);
 $('s-now').innerHTML=`${d>=0?'+':'−'}${Math.abs(d)}%${virt}<small>기준 대비 · 값 ${Math.round(cur)}</small>`;
}
// 장면 6 · 순환 (단계당 0.8초 · 속도 설정을 따른다)
function overLoop(el){
 const step=dur(800)/1000;
 el.innerHTML=`<h1>오늘의 기록 → 내일의 예보</h1>
  <ol class="loop" style="--step:${step}s">
   <li style="animation-delay:${(.1).toFixed(2)}s"><i class="n">01</i><b>오늘 쌓인 것</b><span>주민 기록 ${nReports}건<br>센서 실측</span></li>
   <li style="animation-delay:${(.1+step).toFixed(2)}s"><i class="n">02</i><b>다시 학습</b><span>새 기록을 더해<br>운영자 화면에서 실행</span></li>
   <li style="animation-delay:${(.1+2*step).toFixed(2)}s"><i class="n">03</i><b>비교</b><span>지금 모델 AUC ${D.model.auc.toFixed(2)}<br>사람이 비교해 고름</span></li>
   <li style="animation-delay:${(.1+3*step).toFixed(2)}s"><i class="n">04</i><b>내일 예보</b><span>고른 모델이<br>지도와 기기 일정에 적용</span></li>
  </ol>
  <p class="back-arc" style="animation-delay:${(.1+4*step).toFixed(2)}s">↺ 내일 저녁, 다시 01부터</p>
  <div class="closing"><img src="qr.svg" alt="odor-compass.streamlit.app 로 가는 QR 코드" width="152" height="152">
   <p>악취, 언제 들어올까<small>주민 참여형 AI 앱 코넥트</small><b>odor-compass.streamlit.app</b></p></div>`;
}

// ------------------------------------------------------------------ USB (Web Serial · Chrome/Edge)
const ports={};
async function writeLine(port,s){try{const w=port.writable.getWriter();await w.write(new TextEncoder().encode(s+'\n'));w.releaseLock();}catch(e){}}
async function readLines(port,on){
 const dec=new TextDecoderStream();port.readable.pipeTo(dec.writable).catch(()=>{});const r=dec.readable.getReader();let buf='';
 for(;;){const {value,done}=await r.read();if(done)break;buf+=value;let k;while((k=buf.indexOf('\n'))>=0){on(buf.slice(0,k).trim());buf=buf.slice(k+1);}}
}
// 센서 줄 읽기. 센서 노드 펌웨어(ext/esp32/odor_node)가 시리얼로 값을 내보내게 되면 쓰는 이름(adc_mq137, voc_index)을 먼저 본다.
// 부팅 줄("SHT31 1  SGP40 1 ...")·오류 줄("POST fail 401")은 숫자로 읽지 않는다.
const SENSOR_KEYS=['adc_mq137','mq137','voc_index','mq135','gas','voc','tvoc','raw','value'];
function parseSensor(line){
 if(!line)return;
 try{const j=JSON.parse(line);for(const k of SENSOR_KEYS)if(typeof j[k]==='number'){sensorLabel=k;return j[k];}}catch(e){}
 const m=new RegExp(`\\b(${SENSOR_KEYS.join('|')})\\s*[=:]\\s*(-?\\d+(?:\\.\\d+)?)`,'i').exec(line);if(m){sensorLabel=m[1].toLowerCase();return +m[2];}
 const n=/^-?\d+(?:\.\d+)?$/.exec(line);return n?+n[0]:undefined;
}
window.__demoParseSensor=parseSensor;   // 회귀 확인용(읽기만)
async function connect(kind){
 const st=$(kind+'-state');
 if(!('serial' in navigator)){st.textContent='Chrome · Edge 필요';return;}
 try{const port=await navigator.serial.requestPort();await port.open({baudRate:115200});
  // ESP32 보드는 포트를 열 때 DTR/RTS 로 재부팅될 수 있다. 신호를 내려 두고, 부팅이 끝날 즈음 상태를 한 번 더 보낸다.
  try{await port.setSignals({dataTerminalReady:false,requestToSend:false});}catch(e){}
  ports[kind]=port;st.textContent='연결됨';
  if(kind==='sensor'){stopPractice();resetSamples();readLines(port,l=>{const v=parseSensor(l);if(typeof v==='number'&&isFinite(v))addSample(v);}).catch(()=>{}).finally(sensorLost);}
  else{readLines(port,()=>{});fanOn=null;syncFan();setTimeout(()=>{fanOn=null;syncFan();},3000);}
 }catch(e){st.textContent='연결 안 됨';}
}
function syncFan(){const on=fanShouldRun();if(on===fanOn)return;fanOn=on;if(ports.fan)writeLine(ports.fan,on?'FAN ON':'FAN OFF');}
function stopPractice(){clearInterval(practice);practice=null;$('practice').checked=false;}
if('serial' in navigator)navigator.serial.addEventListener('disconnect',e=>{if(e.target===ports.sensor){ports.sensor=null;sensorLost();}if(e.target===ports.fan){ports.fan=null;$('fan-state').textContent='끊김';}});
// 연습 신호: 화면에 '연습용 가상'으로 표시된다. 처음 6초는 평소 수준, 그다음 30초에 걸쳐 완만하게 오른다.
function startPractice(){
 resetSamples();let t=0,v=120;
 practice=setInterval(()=>{t++;const r=Math.max(0,Math.min(1,(t-24)/120)),rise=r*r*(3-2*r)*38;v+=((120+rise)-v)*.25;addSample(v+Math.sin(t/4)*1.2+(Math.random()-.5)*1.6);},250);
}
$('setup').addEventListener('click',e=>{
 const a=e.target.dataset?.act;if(a==='fan'||a==='sensor')connect(a);if(a==='restart'){$('setup').hidden=true;go(0);}
 const sp=e.target.dataset?.speed;if(sp&&SPEEDS[sp]){speedKey=sp;try{localStorage.setItem('konect.demo.speed',sp);}catch(err){}markSpeed();}
});
function markSpeed(){document.querySelectorAll('#setup [data-speed]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.speed===speedKey)));}
markSpeed();
$('practice').addEventListener('change',e=>{if(e.target.checked)startPractice();else{stopPractice();resetSamples();if(overKind==='sensor')drawSensor();}});

// ------------------------------------------------------------------ 오프라인 지도 (sw.js)
// 리허설 때 본 지도 조각만 이 브라우저에 저장된다. 앱 화면(iframe)이 서비스 워커의 관리를 받도록, 등록이 끝난 뒤에 앱을 띄운다.
async function ensureSW(){
 if(EMBED||!('serviceWorker' in navigator))return;
 try{await navigator.serviceWorker.register('sw.js');
  if(!navigator.serviceWorker.controller)await Promise.race([new Promise(r=>navigator.serviceWorker.addEventListener('controllerchange',r,{once:true})),wait(2500)]);
 }catch(e){}
}
function tileCount(){
 const c=navigator.serviceWorker?.controller;if(!c)return Promise.resolve(null);
 return new Promise(res=>{const t=setTimeout(()=>res(null),1500);
  navigator.serviceWorker.addEventListener('message',function on(e){if(e.data?.type==='count'){clearTimeout(t);navigator.serviceWorker.removeEventListener('message',on);res(e.data.tiles);}});
  c.postMessage({type:'count'});});
}
async function online(){
 try{const ctl=new AbortController();const t=setTimeout(()=>ctl.abort(),3000);
  await fetch(`https://tile.openstreetmap.org/0/0/0.png?probe=${Date.now()}`,{mode:'no-cors',cache:'no-store',signal:ctl.signal});clearTimeout(t);return true;}catch(e){return false;}
}
let mapTimer=null;
async function mapStatus(){
 const [n,on]=await Promise.all([tileCount(),online()]);
 $('map-state').textContent=`지도 저장됨 ${n==null?'—':n+'장'} · 인터넷 ${on?'연결됨':'끊김'}`;
 $('map-state').className=!on&&!n?'warn':'muted';
}
window.__demoMapStatus=mapStatus;   // 확인용
new MutationObserver(()=>{clearInterval(mapTimer);if(!$('setup').hidden){mapStatus();mapTimer=setInterval(mapStatus,5000);}}).observe($('setup'),{attributes:true,attributeFilter:['hidden']});

// ------------------------------------------------------------------ 실제 앱 화면 불러오기
(async()=>{
 await ensureSW();
 const base=new URL(EMBED?'../core.map_component.odor_map/':'../components/odor_map/',location.href).href;
 const html=await (await fetch(base+'index.html',{cache:'no-store'})).text();
 frame.srcdoc=html.replace('<head>',`<head><base href="${base}"><script src="${new URL('shim.js?v=2',location.href).href}"><\/script>`);
})();
$('brand-day').textContent=`${Y}.${M}.${DD} · 운양동`;
if(EMBED){document.querySelectorAll('#setup [data-act=fan],#setup [data-act=sensor],#fan-state,#sensor-state').forEach(e=>e.hidden=true);$('usb-note').hidden=false;$('map-state').hidden=true;}
setClock();$('count').textContent=`1 / ${SCENES.length}`;$('scene-name').textContent=SCENES[0].name;
window.__demo={get scene(){return i;},get cardAction(){return card?.act?.button||null;},get busy(){return !cardFn;}};   // 확인용(읽기만)
})();
