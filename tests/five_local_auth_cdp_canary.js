/* Checks *actual* authenticated Meet navigation in four private Chrome
 * instances, not merely the presence of stale Google cookie markers.
 * No meeting creation, recording, user content or credentials.
 */
'use strict';
const {chromium}=require('playwright');
(async()=>{
 for(const i of [2,3,4,5]){
  const b=await chromium.connectOverCDP('http://beonmeet-isolated-chrome-'+i+':9223',{timeout:12000});
  try{
   const c=b.contexts()[0];
   if(!c)throw Error('No persistent Chrome context for lane '+i);
   const page=await c.newPage();
   try{
     await page.goto('https://meet.google.com/?hl=en',{waitUntil:'domcontentloaded',timeout:40000});
     await page.waitForTimeout(1400);
     const valid=new URL(page.url()).hostname==='meet.google.com';
     console.log('FIVE_GOOGLE_LANE_AUTHENTICATED',i,valid);
     if(!valid)process.exitCode=2;
   }finally{await page.close().catch(()=>{})}
  }finally{await b.close().catch(()=>{})}
 }
})().catch(err=>{
 console.error('FIVE_GOOGLE_LANE_AUTH_CANARY_FAILED',err.name);
 process.exitCode=2;
});
