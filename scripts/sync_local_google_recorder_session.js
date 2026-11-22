'use strict';
/* Synchronize Google recorder's OWN authorized browser session on this VPS.
 * Reads decrypted Google cookies only in process memory via existing CDP and
 * sets them into four staged private Chrome profiles on the same local Docker
 * network. NEVER print, persist or transmit cookie values to logs/CI.
 * Only run while workers idle; no production routing changes.
 */
const {chromium}=require('playwright');
const fs=require('fs');
const urls=JSON.parse(fs.readFileSync('/qa-existing-links.json','utf8')).links;
function checkButtons(page){
 return page.evaluate(()=>{
  const labels=Array.from(document.querySelectorAll('button,[role=button]'))
    .map(e=>String(e.getAttribute('aria-label')||e.textContent||'').trim().toLowerCase());
  const has=(...words)=>labels.some(s=>words.some(w=>s.includes(w)));
  return {
   joinNow:has('join now','jetzt teilnehmen','rejoindre','پیوستن'),
   askToJoin:has('ask to join','teilnahme erbitten','demander à participer','درخواست پیوستن'),
   signIn:has('sign in','anmelden','se connecter','ورود'),
   inCall:has('leave call','anruf verlassen')
  };
 });
}
async function status(context,url){
 const page=await context.newPage();
 try{
  const res=await page.goto(url,{waitUntil:'domcontentloaded',timeout:35000});
  await page.waitForTimeout(1200);
  const u=new URL(page.url());
  const isRoom=u.hostname==='meet.google.com'&&/^\/[a-z]{3}-[a-z]{4}-[a-z]{3}/.test(u.pathname);
  const state=await checkButtons(page);
  return {isRoom,okStatus:res?.status()===200,...state};
 }finally{await page.close().catch(()=>{})}
}
function isSigned(state){
 return state.isRoom&&state.okStatus&&!state.signIn&&state.joinNow;
}
async function connect(host){
 return chromium.connectOverCDP('http://'+host+':9223',{timeout:16000});
}
(async()=>{
 if(urls.length!==5||new Set(urls).size!==5)throw Error('QA link fixture invalid');
 const source=await connect('beonmeet-chrome-single');
 try{
  const original=source.contexts()[0];
  if(!original)throw Error('Original Chrome context missing');
  const sourceState=await status(original,urls[0]);
  console.log('LOCAL_GOOGLE_RECORDER_SOURCE_MEET_READY',isSigned(sourceState));
  if(!isSigned(sourceState))throw Error('Original recorder does not currently have a verified Meet session');
  const allCookies=await original.cookies();
  const googleCookies=allCookies.filter(c=>{
   const domain=String(c.domain||'').replace(/^\./,'').toLowerCase();
   return domain==='google.com'||domain.endsWith('.google.com');
  });
  if(!googleCookies.some(c=>['SID','__Secure-1PSID','__Secure-3PSID'].includes(c.name)))
   throw Error('No eligible authenticated Google session cookies found');
  console.log('LOCAL_GOOGLE_SESSION_SOURCE_PRESENT',true);
  for(let n=2;n<=5;n++){
   const dest=await connect('beonmeet-isolated-chrome-'+n);
   try{
    const context=dest.contexts()[0];
    if(!context)throw Error('Isolated Chrome context missing');
    const before=await status(context,urls[n-1]);
    if(isSigned(before)){
     console.log('LOCAL_GOOGLE_SESSION_LANE',n,'already-authenticated');
     continue;
    }
    if(!before.isRoom)throw Error('Isolated Chrome cannot load QA Meet room');
    await context.addCookies(googleCookies);
    await new Promise(resolve=>setTimeout(resolve,700));
    const after=await status(context,urls[n-1]);
    const passed=isSigned(after);
    console.log('LOCAL_GOOGLE_SESSION_LANE',n,'signed-in-meet',passed);
    if(!passed)throw Error('Isolated lane '+n+' remains in guest state');
   }finally{await dest.close().catch(()=>{})}
  }
  if(!isSigned(await status(original,urls[0])))
   throw Error('Original Chrome lost its Meet authentication');
  console.log('LOCAL_GOOGLE_RECORDER_FIVE_LANES_SIGNED_IN_PASS');
 }finally{await source.close().catch(()=>{})}
})().catch(e=>{
 console.error('LOCAL_GOOGLE_SESSION_SYNC_FAIL_CLOSED',e.name);
 process.exitCode=2;
});
