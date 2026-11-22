/* Authorized isolated test: mint ONE disposable Meet link via meet.new without invitees.
   The link is ONLY written to a root-owned file on the VPS, never to CI logs.
*/
'use strict';
const {chromium}=require('playwright');
(async()=>{
const b=await chromium.connectOverCDP('http://beonmeet-isolated-chrome-2:9223',{timeout:18000});
let page;
try{
  const c=b.contexts()[0];
  if(!c)throw Error('No authenticated persistent Chrome context');
  page=await c.newPage();
  await page.goto('https://meet.new/',{waitUntil:'domcontentloaded',timeout:50000});
  const pattern=/https:\/\/meet\.google\.com\/([a-z]{3}-[a-z]{4}-[a-z]{3})(?:[/?#]|$)/i;
  let url='';
  for(let i=0;i<20;i++){
    const candidate=page.url();
    const match=candidate.match(pattern);
    if(match){url='https://meet.google.com/'+match[1].toLowerCase();break;}
    await page.waitForTimeout(1000);
  }
  if(!url)throw Error('Meet.new did not return a meeting code');
  process.stdout.write(JSON.stringify({link:url})+'\n');
}finally{
  if(page)await page.close().catch(()=>{});
  await b.close().catch(()=>{});
}
})().catch(e=>{console.error('MEET_NEW_CANARY_FAILURE_TYPE '+e.name);process.exitCode=2;});
