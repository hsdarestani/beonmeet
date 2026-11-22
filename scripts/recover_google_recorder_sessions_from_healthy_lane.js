'use strict';
/* Recover only the user's own BeOnMeet Google recorder browser sessions on the
 * SAME VPS and private Docker network. This routine must run after an idle
 * controller/worker health guard. It never prints or persists cookie values,
 * account identifiers, meeting codes or user data; do not run during recordings.
 *
 * We cannot assume the original browser is still logged in: Google can rotate
 * sessions after multiple Chrome profiles share an authenticated account.
 */
const {chromium}=require('playwright'),fs=require('fs');
const fixture=JSON.parse(fs.readFileSync('/qa-existing-links.json','utf8')).links;
const lanes=[
 {id:1,host:'beonmeet-chrome-single',url:fixture[0]},
 ...[2,3,4,5].map(n=>({id:n,host:'beonmeet-isolated-chrome-'+n,url:fixture[n-1]}))
];
async function connect(host){return chromium.connectOverCDP('http://'+host+':9223',{timeout:16000})}
async function meetStatus(ctx,url){
 const page=await ctx.newPage();
 try{
  const r=await page.goto(url,{waitUntil:'domcontentloaded',timeout:37000});
  await page.waitForTimeout(1200);
  const address=new URL(page.url());
  const inside=address.hostname==='meet.google.com'&&/^\/[a-z]{3}-[a-z]{4}-[a-z]{3}/.test(address.pathname);
  const ui=await page.evaluate(()=>{
   const labels=[...document.querySelectorAll('button,[role=button]')]
    .map(e=>String(e.getAttribute('aria-label')||e.textContent||'').trim().toLowerCase());
   const has=(...args)=>labels.some(s=>args.some(w=>s.includes(w)));
   return {
    joinNow:has('join now','jetzt teilnehmen','rejoindre','پیوستن'),
    signIn:has('sign in','anmelden','se connecter','ورود')
   };
  });
  return inside&&r?.status()===200&&ui.joinNow&&!ui.signIn;
 }finally{await page.close().catch(()=>{})}
}
(async()=>{
 if(fixture.length!==5||new Set(fixture).size!==5)throw Error('Private QA fixture unavailable');
 const status=[];
 for(const lane of lanes){
  const b=await connect(lane.host);
  try{
   const c=b.contexts()[0];if(!c)throw Error('No persistent Chrome context');
   status.push({id:lane.id,ready:await meetStatus(c,lane.url)});
  }finally{await b.close().catch(()=>{})}
 }
 console.log('RECORDER_AUTH_READINESS_BEFORE',JSON.stringify(status));
 let source=null;
 // Prefer any actual authenticated browser, not the previously assumed source.
 for(const item of status){
  if(item.ready){source=lanes.find(l=>l.id===item.id);break}
 }
 if(!source)throw Error('No signed-in BeOnMeet browser remains; owner reauthentication needed');
 console.log('RECORDER_AUTH_SOURCE_LANE',source.id);
 const origin=await connect(source.host);
 try{
  const ctx=origin.contexts()[0];
  if(!ctx||!await meetStatus(ctx,source.url))throw Error('Source authentication changed during scan');
  const cookies=(await ctx.cookies()).filter(x=>{
   const d=String(x.domain||'').replace(/^\./,'').toLowerCase();
   return d==='google.com'||d.endsWith('.google.com');
  });
  if(!cookies.some(x=>['SID','__Secure-1PSID','__Secure-3PSID'].includes(x.name)))
   throw Error('Validated session cookie marker absent');
  for(const lane of lanes){
   if(lane.id===source.id||status.some(x=>x.id===lane.id&&x.ready))continue;
   const b=await connect(lane.host);
   try{
    const c=b.contexts()[0];if(!c)throw Error('No persistent context lane '+lane.id);
    await c.addCookies(cookies);
    await new Promise(resolve=>setTimeout(resolve,600));
    const ok=await meetStatus(c,lane.url);
    console.log('RECORDER_AUTH_LANE_RECOVERED',lane.id,ok);
    if(!ok)throw Error('Failed to recover isolated Chrome lane '+lane.id);
   }finally{await b.close().catch(()=>{})}
  }
 }finally{await origin.close().catch(()=>{})}
 for(const lane of lanes){
  const b=await connect(lane.host);
  try{
   const c=b.contexts()[0];
   const ok=!!c&&await meetStatus(c,lane.url);
   console.log('RECORDER_AUTH_LANE_FINAL',lane.id,ok);
   if(!ok)throw Error('Lane '+lane.id+' auth regression');
  }finally{await b.close().catch(()=>{})}
 }
 console.log('RECORDER_AUTH_FIVE_LANES_VERIFIED_NO_CONTROLLER_CHANGE');
})().catch(e=>{
 console.error('RECORDER_AUTH_RECOVERY_FAILED',e.name,(/owner reauthentication/.test(String(e.message))?'OWNER_LOGIN_REQUIRED':'QA_OR_SESSION_ERROR'));
 process.exitCode=2;
});
