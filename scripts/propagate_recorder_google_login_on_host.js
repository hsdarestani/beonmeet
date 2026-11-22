/* Post-login, on-host-only propagation of the BeOnMeet recorder's own
 * authenticated Google session to four private, separately isolated browsers.
 *
 * This touches no user browser, transmits nothing off-host, writes no account
 * tokens to logs or Git, and refuses to touch existing already signed-in lanes.
 * Requires idle production and owner reauthentication of original Chrome.
 */
'use strict';
const {chromium}=require('playwright');
async function connect(host){return chromium.connectOverCDP('http://'+host+':9223',{timeout:13000})}
async function authenticated(context){
 const p=await context.newPage();
 try{
  await p.goto('https://meet.google.com/?hl=en',{waitUntil:'domcontentloaded',timeout:40000});
  await p.waitForTimeout(1800);
  return new URL(p.url()).hostname==='meet.google.com';
 }finally{await p.close().catch(()=>{})}
}
(async()=>{
 const source=await connect('beonmeet-chrome-single');
 try{
  const original=source.contexts()[0];
  if(!original||!await authenticated(original))throw Error('SOURCE_GOOGLE_LOGIN_EXPIRED');
  const candidates=await original.cookies();
  const google=candidates.filter(x=>{
   const d=String(x.domain||'').replace(/^\./,'').toLowerCase();
   return d==='google.com'||d.endsWith('.google.com');
  });
  if(!google.some(x=>['SID','__Secure-1PSID','__Secure-3PSID'].includes(x.name)))
     throw Error('SOURCE_AUTH_SESSION_COOKIES_UNAVAILABLE');
  console.log('GOOGLE_SESSION_SOURCE_VERIFIED');
  for(const n of [2,3,4,5]){
   const dest=await connect('beonmeet-isolated-chrome-'+n);
   try{
    const c=dest.contexts()[0];if(!c)throw Error('NO_DEST_BROWSER_CONTEXT');
    if(await authenticated(c)){
      console.log('GOOGLE_SESSION_LANE_ALREADY_AUTHENTICATED',n);
      continue;
    }
    await c.addCookies(google);
    const ok=await authenticated(c);
    console.log('GOOGLE_SESSION_LANE_VALIDATED',n,ok);
    if(!ok)throw Error('LANE_GOOGLE_AUTH_STILL_INVALID_'+n);
   }finally{await dest.close().catch(()=>{})}
  }
  if(!await authenticated(original))throw Error('ORIGINAL_SESSION_LOST_AFTER_RESTORE');
  console.log('GOOGLE_SESSION_FIVE_CHROMES_AUTHENTICATED');
 }finally{await source.close().catch(()=>{})}
})().catch(e=>{console.error('GOOGLE_SESSION_REAUTH_QA_FAILED',e.message);process.exitCode=2;});