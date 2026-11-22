/* One-time surgical BeOnMeet Chrome repair. Leaves container, login profile,
 * customer sessions and CamCam intact. Only operates on the currently blocked
 * accounts.google.com tab, and only if there is exactly one page target.
 * Requires externally checked idle controller and workers.
 */
'use strict';
const {chromium}=require('playwright');
const WebSocket=require('ws');
(async()=>{
 const base='http://beonmeet-chrome-single:9223';
 const reply=await fetch(base+'/json/version',{signal:AbortSignal.timeout(6000)});
 if(!reply.ok)throw Error('Chrome DevTools HTTP unavailable');
 const info=await reply.json();
 const ws=new WebSocket(info.webSocketDebuggerUrl,{handshakeTimeout:7000});
 let id=1;
 const pending=new Map();
 ws.on('message',event=>{
  try{
   const data=JSON.parse(event.toString());
   if(pending.has(data.id)){
    const entry=pending.get(data.id);pending.delete(data.id);clearTimeout(entry.timer);
    data.error?entry.reject(Error('Chrome CDP command rejected')):entry.resolve(data.result);
   }
  }catch(e){}
 });
 const close=()=>ws.close();
 try{
  await new Promise((resolve,reject)=>{
   ws.once('open',resolve);
   ws.once('error',reject);
   setTimeout(()=>reject(Error('Chrome raw WebSocket did not open')),9000);
  });
  function send(method,params={}){
   return new Promise((resolve,reject)=>{
    const requestId=id++;
    const timer=setTimeout(()=>{pending.delete(requestId);reject(Error('Chrome '+method+' timed out'))},9000);
    pending.set(requestId,{resolve,reject,timer});
    ws.send(JSON.stringify({id:requestId,method,params}));
   });
  }
  const targetInfo=await send('Target.getTargets');
  const pages=targetInfo.targetInfos.filter(t=>t.type==='page');
  const safeHost=uri=>{try{return new URL(uri).hostname}catch{return ''}};
  console.log('CDP_TAB_RECOVERY_PAGE_COUNT',pages.length);
  if(pages.length!==1||safeHost(pages[0].url)!=='accounts.google.com'){
   console.log('CDP_TAB_RECOVERY_GUARD_ABORT_DIFFERENT_PAGE');
   process.exitCode=3;return;
  }
  // Ensure a page remains so Chrome does not exit after closing login chooser.
  const created=await send('Target.createTarget',{url:'about:blank'});
  if(!created?.targetId||created.targetId===pages[0].targetId)throw Error('Could not create replacement Chrome page');
  console.log('CDP_TAB_RECOVERY_BLANK_TAB_CREATED');
  const closed=await send('Target.closeTarget',{targetId:pages[0].targetId});
  if(!closed?.success)throw Error('Chrome refused to close blocked account tab');
  console.log('CDP_TAB_RECOVERY_BLOCKED_LOGIN_TAB_CLOSED');
 }finally{close()}
 await new Promise(r=>setTimeout(r,1200));
 const tabs=await (await fetch(base+'/json/list',{signal:AbortSignal.timeout(6000)})).json();
 const remaining=tabs.filter(t=>t.type==='page');
 console.log('CDP_TAB_RECOVERY_REMAINING_PAGES',remaining.length);
 if(remaining.length!==1||remaining[0].url!=='about:blank')
  throw Error('Chrome replacement tab verification failed');
 const browser=await chromium.connectOverCDP(base,{timeout:20000});
 try{console.log('CDP_TAB_RECOVERY_PLAYWRIGHT_CONNECTED',browser.contexts().length)}
 finally{await browser.close().catch(()=>{})}
 console.log('CDP_TAB_RECOVERY_SUCCESS_PROFILE_UNCHANGED');
})().catch(e=>{console.log('CDP_TAB_RECOVERY_FAILED',e.name,String(e.message||'').split(':')[0].slice(0,95));process.exitCode=2});
