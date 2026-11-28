'use strict';
/* Read-only auth proof on IDLE authorized BeOnMeet Chrome profiles.
 * Never print cookies, account identity, QA Meet URLs or page content. */
const fs=require('fs'),{chromium}=require('playwright');
const names={
  '9126':['beonmeet-chrome-single',0],
  '9132':['beonmeet-isolated-chrome-2',1],
  '9133':['beonmeet-isolated-chrome-3',2],
  '9134':['beonmeet-isolated-chrome-4',3],
  '9135':['beonmeet-isolated-chrome-5',4]
};
function isRoom(target){
 const u=new URL(target);
 return u.hostname==='meet.google.com'&&/^\/[a-z]{3}-[a-z]{4}-[a-z]{3}$/.test(u.pathname);
}
async function check(port,link){
 const host=names[port][0];let browser,page;
 try{
  browser=await chromium.connectOverCDP('http://'+host+':9223',{timeout:11000});
  const context=browser.contexts()[0];if(!context)throw Error('NO_CONTEXT');
  page=await context.newPage();
  const response=await page.goto(link,{waitUntil:'domcontentloaded',timeout:33000});
  await page.waitForFunction(()=>{
   const labels=[...document.querySelectorAll('button,[role=button]')].map(x=>String(x.getAttribute('aria-label')||x.textContent||'').trim().toLowerCase());
   return labels.some(x=>['join now','jetzt teilnehmen','rejoindre','پیوستن','ask to join','teilnahme erbitten','sign in','anmelden','se connecter'].some(w=>x.includes(w)));
  },null,{timeout:6500}).catch(()=>{});
  const valid=isRoom(page.url())&&response?.status()===200;
  const ui=await page.evaluate(()=>{
   const labels=[...document.querySelectorAll('button,[role=button]')]
     .map(x=>String(x.getAttribute('aria-label')||x.textContent||'').trim().toLowerCase());
   const has=(...words)=>labels.some(x=>words.some(word=>x.includes(word)));
   return {
    joined:has('join now','jetzt teilnehmen','rejoindre','پیوستن'),
    guest:has('ask to join','teilnahme erbitten','demander à participer','درخواست پیوستن'),
    signin:has('sign in','anmelden','se connecter','ورود')
   };
  });
  return !!(valid&&ui.joined&&!ui.guest&&!ui.signin);
 }catch(e){return false}
 finally{
  if(page)await page.close().catch(()=>{});
  if(browser)await browser.close().catch(()=>{});
 }
}
(async()=>{
 const spec=JSON.parse(fs.readFileSync('/qa-input.json','utf8'));
 const links=JSON.parse(fs.readFileSync('/qa-links.json','utf8')).links;
 if(!Array.isArray(spec.ports)||!Array.isArray(links)||links.length!==5||spec.ports.length>5)
  throw Error('Invalid private watchdog input');
 const result={workers:{}};
 async function scan(n){
  const port=String(n);
  if(!Object.prototype.hasOwnProperty.call(names,port))throw Error('Unexpected worker port');
  const link=links[names[port][1]];
  if(!/^https:\/\/meet\.google\.com\/[a-z]{3}-[a-z]{4}-[a-z]{3}$/.test(link))
   throw Error('Invalid test link');
  result.workers['http://127.0.0.1:'+port]={
    ready:await check(port,link),checked_at:Math.round(Date.now()/1000)
  };
 }
 // Limit concurrency to two idle browsers; never use unbounded fan-out.
 for(let i=0;i<spec.ports.length;i+=2)await Promise.all(spec.ports.slice(i,i+2).map(scan));
 process.stdout.write(JSON.stringify(result)+'\n');
})().catch(e=>{console.error('AUTH_MONITOR_FAILED',e.name);process.exitCode=2});
