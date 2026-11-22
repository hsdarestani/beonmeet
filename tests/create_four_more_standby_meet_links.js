/* Generate four more UNIQUE, disposable Meet test-room URLs without invitations.
 * Output is redirected into a root-only file on the VPS, never printed in CI.
 */
'use strict';
const {chromium}=require('playwright');
(async()=>{
const b=await chromium.connectOverCDP('http://beonmeet-isolated-chrome-2:9223',{timeout:18000});
const links=[];
try{
  const c=b.contexts()[0];
  if(!c)throw Error('Chrome persistent context unavailable');
  for(let i=0;i<4;i++){
    const p=await c.newPage();
    try{
      await p.goto('https://meet.new/',{waitUntil:'domcontentloaded',timeout:45000});
      let uri='';
      for(let n=0;n<20;n++){
        const match=p.url().match(/^https:\/\/meet\.google\.com\/([a-z]{3}-[a-z]{4}-[a-z]{3})(?:[/?#]|$)/);
        if(match){uri='https://meet.google.com/'+match[1];break;}
        await p.waitForTimeout(900);
      }
      if(!uri||links.includes(uri))throw Error('No unique Meet link was created');
      links.push(uri);
    }finally{await p.close().catch(()=>{});}
  }
  process.stdout.write(JSON.stringify({links})+'\n');
}finally{await b.close().catch(()=>{});}
})().catch(e=>{console.error('MEET_TEST_LINKS_FAILED '+e.name);process.exitCode=2;});
