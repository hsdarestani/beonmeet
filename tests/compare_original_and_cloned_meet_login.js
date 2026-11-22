/* Compare actual navigation of original/cloned Google CDP profiles.
 * Do not read cookie values or user content. New temporary tabs only. */
'use strict';
const {chromium}=require('playwright');
async function profile(name,host){
 const browser=await chromium.connectOverCDP('http://'+host+':9223',{timeout:10000});
 try{
  const context=browser.contexts()[0];if(!context)throw Error('No persistent context');
  const p=await context.newPage();
  try{
   const cookies=await context.cookies('https://accounts.google.com','https://meet.google.com');
   const names=new Set(cookies.map(c=>c.name));
   await p.goto('https://meet.google.com/',{waitUntil:'domcontentloaded',timeout:35000}).catch(()=>{});
   await p.waitForTimeout(1600);
   const url=new URL(p.url());
   console.log('MEET_PROFILE_SIGNIN_PROBE',JSON.stringify({
     lane:name,
     googleAuthCookieMarker:['SID','__Secure-1PSID','__Secure-3PSID'].some(n=>names.has(n)),
     destination:url.hostname,
     meetPage:url.hostname==='meet.google.com',
     marketingPage:url.hostname==='workspace.google.com',
     accountLogin:url.hostname==='accounts.google.com'
   }));
  }finally{await p.close().catch(()=>{})}
 }finally{await browser.close().catch(()=>{})}
}
(async()=>{
 for(const [name,host] of [
  ['original','beonmeet-chrome-single'],
  ...[2,3,4,5].map(n=>[String(n),'beonmeet-isolated-chrome-'+n])
 ]){
  try{await profile(name,host)}catch(e){console.log('MEET_PROFILE_SIGNIN_PROBE_ERROR',name,e.name)}
 }
})().catch(e=>{console.error('MEET_PROFILE_DIAG_FATAL',e.name);process.exitCode=2});