'use strict';
// 코넥트 시연 웹 전용 서비스 워커 (범위: /demo/).
// 리허설 때 실제로 본 지도 조각(OSM)과 글꼴만 이 브라우저에 저장해 두고, 인터넷이 없을 때 저장본을 돌려준다.
// 미리 대량으로 내려받지 않는다(OSM 타일 사용 정책). 저장본도 인터넷도 없으면 빈 조각을 돌려줘서 구역 면만 보이게 한다.
const TILES='konect-demo-tiles-v1',FONTS='konect-demo-fonts-v1';
const isTile=u=>u.hostname==='tile.openstreetmap.org'&&/^\/\d+\/\d+\/\d+\.png$/.test(u.pathname)&&!u.search;
const isFont=u=>u.hostname==='fonts.googleapis.com'||u.hostname==='fonts.gstatic.com';
// 1×1 투명 PNG: 저장본이 없고 인터넷도 없을 때 '지도 연결 실패' 대신 빈 바탕
const BLANK=Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII='),c=>c.charCodeAt(0));

self.addEventListener('install',()=>self.skipWaiting());
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
self.addEventListener('fetch',e=>{
 const u=new URL(e.request.url);
 if(isTile(u))e.respondWith(cacheFirst(TILES,e.request,true));
 else if(isFont(u))e.respondWith(cacheFirst(FONTS,e.request,false));
});
async function cacheFirst(name,req,blank){
 const cache=await caches.open(name);
 const hit=await cache.match(req,{ignoreVary:true});
 if(hit)return hit;
 try{
  const res=await fetch(req);
  if(res.ok||res.type==='opaque')cache.put(req,res.clone()).catch(()=>{});
  return res;
 }catch(err){
  if(blank)return new Response(BLANK,{status:200,headers:{'Content-Type':'image/png','X-Demo':'blank'}});
  throw err;
 }
}
// 시연 페이지가 묻는 것: 저장된 지도 조각 수
self.addEventListener('message',async e=>{
 if(e.data?.type!=='count')return;
 const n=(await (await caches.open(TILES)).keys()).length;
 e.source?.postMessage({type:'count',tiles:n});
});
