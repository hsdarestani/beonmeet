/* Safe nonmutating Google Meet homepage readiness inspection on one STANDBY Chrome.
   Does not open/join meetings, inspect user files, or print Google account data.
*/
'use strict';
const {chromium}=require('playwright');
(async()=>{
const b=await chromium.connectOverCDP('http://beonmeet-isolated-chrome-2:9223',{timeout:15000});
let page;
try{
  const c=b.contexts()[0];
  if(!c)throw Error('Persistent Chrome context missing');
  page=await c.newPage();
  await page.goto('https://meet.google.com/',{waitUntil:'domcontentloaded',timeout:45000});
  await page.waitForTimeout(2200);
  const target=page.url();
  console.log('GOOGLE_MEET_HOME_REACHABLE',target.startsWith('https://meet.google.com'));
  console.log('GOOGLE_MEET_LOGIN_REDIRECT',target.includes('accounts.google.com'));
  const controls=await page.evaluate(()=>Array.from(document.querySelectorAll('button,[role="button"]'))
    .map(e=>(e.getAttribute('aria-label')||e.textContent||'').trim().replace(/\s+/g,' '))
    .filter(s=>s.length>0&&s.length<85)
    .filter(s=>/new meeting|create a meeting|start an instant|for later|besprechung|جلسه|réunion|join|be­sprechung/i.test(s))
    .slice(0,14));
  console.log('GOOGLE_MEET_GENERIC_ACTIONS',JSON.stringify(controls));
}finally{
  if(page)await page.close().catch(()=>{});
  await b.close().catch(()=>{});
}
})().catch(err=>{console.error('GOOGLE_MEET_UI_CANARY_FAILED',err.name);process.exitCode=2;});
