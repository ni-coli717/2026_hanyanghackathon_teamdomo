'use strict';
// 시연 웹 전용. 실제 앱 화면(components/odor_map) 안에서 앱 코드보다 먼저 실행된다.
// 앱 코드는 한 줄도 바꾸지 않고, 앱이 바깥에서 받는 것 네 가지만 시연용으로 바꿔 끼운다:
//   시계(2026-09-03) · 내 위치(운양역) · 기기 서버 응답(그날 일정) · 브라우저 저장소(이 탭 안에서만)
(function(){
const host=window.parent.DEMO_HOST;
// 1) 시계: 지금 = 시연 시각. 흐르는 속도는 그대로.
const RealDate=Date;let offset=host.now()-RealDate.now();
class DemoDate extends RealDate{
 constructor(...a){if(a.length===0)super(RealDate.now()+offset);else super(...a);}
 static now(){return RealDate.now()+offset;}
}
window.Date=DemoDate;
// 2) 내 위치: 부스는 운양동이 아니므로, 시연 속 주민의 위치를 돌려준다.
const geo={getCurrentPosition(ok){const p=host.position();setTimeout(()=>ok({coords:{latitude:p[0],longitude:p[1],accuracy:12},timestamp:Date.now()}),700);},watchPosition(){return 0;},clearWatch(){}};
try{Object.defineProperty(navigator,'geolocation',{value:geo,configurable:true});}catch(e){}
// 3) 브라우저 저장소: 이 탭의 메모리에만 둔다(실제 앱 로그인·기기 연결 정보를 건드리지 않게).
const mem=new Map(Object.entries(host.storage()));
const store={getItem:k=>mem.has(k)?mem.get(k):null,setItem:(k,v)=>{mem.set(k,String(v));},removeItem:k=>{mem.delete(k);},clear:()=>mem.clear(),key:i=>[...mem.keys()][i]??null,get length(){return mem.size;}};
try{Object.defineProperty(window,'localStorage',{value:store,configurable:true});}catch(e){}
// 4) 기기 서버: device_get / device_set 만 시연 응답으로. 그 밖의 요청(지도 타일 등)은 그대로 나간다.
const realFetch=window.fetch.bind(window);
window.fetch=(url,opt)=>{
 const m=/\/rest\/v1\/rpc\/(device_\w+)/.exec(String(url));
 if(!m)return realFetch(url,opt);
 let body={};try{body=JSON.parse(opt?.body||'{}');}catch(e){}
 const out=host.deviceRpc(m[1],body);
 return Promise.resolve(new Response(JSON.stringify(out??null),{status:200,headers:{'Content-Type':'application/json'}}));
};
// 발표자 키(→ ← PageDown PageUp, 숫자, S)는 지도가 아니라 시연 진행으로 보낸다.
window.addEventListener('keydown',e=>{
 if(/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName))return;
 if(host.key(e)){e.preventDefault();e.stopImmediatePropagation();}
},true);
window.__demo={setNow(ms){offset=ms-RealDate.now();}};
})();
