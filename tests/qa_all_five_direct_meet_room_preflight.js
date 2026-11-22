'use strict';
/* Preflight five private, independent Chrome Meet rooms. Never log meeting
 * codes, Google IDs, cookies or page content. Never click Join/Ask to Join.
 * Retry transient navigation races once, but fail if any browser lacks a
 * genuine Meet prejoin UI. This DOES NOT establish host admission or recording.
 */
const {chromium}=require('playwright'),fs=require('fs');
function where(url){
 try{
  const u=new URL(url);
  if(u.hostname==='meet.google.com')return /^\/[a-z]{3}-[a-z]{4}-[a-z]{3}/i.test(u.pathname)?'room':'landing';
  if(u.hostname==='accounts.google.com')return 'sign-in-page';
  if(u.hostname==='workspace.google.com')return 'marketing';
  return 'other-domain';
 }catch{return 'invalid-url'}
}
function errCategory(e){
 const s=String(e?.message||'').toLowerCase();
 if(s.includes('target closed')||s.includes('browser has been closed'))return 'browser-target-closed';
 if(s.includes('execution context was destroyed')||s.includes('navigation'))return 'navigation-race';
 if(s.includes('timeout')||e?.name==='TimeoutError')return 'navigation-timeout';
 if(s.includes('prejoin not ready'))return 'prejoin-unavailable';
 if(s.includes('connect'))return 'cdp-connection';
 return 'other';
}
(async()=>{
 const links=JSON.parse(fs.readFileSync('/qa-existing-links.json','utf8')).links;
 if(!Array.isArray(links)||links.length!==5||new Set(links).size!==5)throw Error('test-link-list-invalid');
 const failed=[];
 for(let i=0;i<5;i++){
  const lane=i===0?'original':String(i+1);
  const host=i===0?'beonmeet-chrome-single':'beonmeet-isolated-chrome-'+(i+1);
  let ready=false;
  for(let attempt=1;attempt<=2&&!ready;attempt++){
   let b,p,step='cdp';
   try{
    b=await chromium.connectOverCDP('http://'+host+':9223',{timeout:13000});
    const ctx=b.contexts()[0];if(!ctx)throw Error('no-context');
    step='new-page';
    p=await ctx.newPage();
    const visited=[];
    p.on('framenavigated',f=>{if(f===p.mainFrame()&&visited.length<8)visited.push(where(f.url()))});
    step='navigate';
    const res=await p.goto(links[i],{waitUntil:'domcontentloaded',timeout:30000});
    await p.waitForTimeout(1250);
    step='check-ui';
    const ui=await p.evaluate(()=>{
      const texts=Array.from(document.querySelectorAll('button,[role=button]'))
        .map(e=>String(e.getAttribute('aria-label')||e.textContent||'').trim().toLowerCase());
      const match=(...words)=>texts.some(s=>words.some(w=>s.includes(w)));
      const body=String(document.body?.innerText||'').toLowerCase();
      return {
        buttons:texts.length,
        joinNow:match('join now','jetzt teilnehmen','rejoindre','پیوستن'),
        askToJoin:match('ask to join','teilnahme erbitten','demander à participer','درخواست پیوستن'),
        leaveCall:match('leave call','anruf verlassen','quitter l’appel'),
        signIn:match('sign in','anmelden','se connecter','ورود'),
        expired:/meeting (does not exist|not found|has ended)|besprechung existiert nicht|this meeting is no longer|invalid meeting/.test(body)
      };
    });
    const final=where(p.url());
    console.log('MEET_QA_LANE_PREFLIGHT',JSON.stringify({lane,attempt,final,status:res?.status()||0,visited,ui}));
    ready=final==='room'&&res?.status()===200&&!ui.expired&&ui.joinNow&&!ui.signIn;
    if(!ready)console.log('MEET_QA_LANE_PREJOIN_NOT_READY',lane);
   }catch(e){
    console.log('MEET_QA_LANE_TRANSIENT',JSON.stringify({lane,attempt,stage:step,type:e.name,category:errCategory(e)}));
   }finally{
    if(p)await p.close().catch(()=>{});
    if(b)await b.close().catch(()=>{});
   }
   if(!ready&&attempt===1)await new Promise(r=>setTimeout(r,1000));
  }
  if(!ready)failed.push(lane);
 }
 if(failed.length)throw Error('one-or-more-lanes-not-ready');
 console.log('FIVE_PRIVATE_GOOGLE_MEET_SIGNED_IN_JOIN_NOW_PASS');
})().catch(e=>{console.log('MEET_QA_LANE_PREFLIGHT_FAILED',e.code||e.name);process.exitCode=2});
