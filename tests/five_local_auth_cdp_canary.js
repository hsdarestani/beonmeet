/* Checks CDP connectivity and Google auth cookie presence without reading values.
 * No new Google Meet rooms are joined and no recordings or user messages are read.
 */
'use strict';
const {chromium}=require('playwright');
(async()=>{
 for(const i of [2,3,4,5]){
  const b=await chromium.connectOverCDP('http://beonmeet-isolated-chrome-'+i+':9223',{timeout:12000});
  try{
   const c=b.contexts()[0];
   if(!c)throw Error('No persistent Chrome context for lane '+i);
   const cookies=await c.cookies(['https://accounts.google.com','https://meet.google.com']);
   const signed=cookies.some(x=>['SID','HSID','SSID','SAPISID','__Secure-1PSID','__Secure-3PSID'].includes(x.name));
   console.log('FIVE_GOOGLE_LANE_AUTH_COOKIE_MARKER '+i+' '+(signed?'present':'missing')+' count='+cookies.length);
   if(!signed)process.exitCode=2;
  }finally{await b.close().catch(()=>{});}
 }
})().catch(err=>{console.error('FIVE_GOOGLE_LANE_AUTH_CANARY_FAILED '+err.message);process.exitCode=2;});
