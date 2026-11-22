/* Read-only diagnostic on isolated QA Chrome; never print account details,
   cookie values, meeting links, page body or personal content. */
'use strict';
const { chromium }=require('playwright');
(async()=>{
 const b=await chromium.connectOverCDP('http://beonmeet-isolated-chrome-3:9223',{timeout:14000});
 const c=b.contexts()[0];if(!c)throw Error('No browser context');
 for(const endpoint of ['https://meet.google.com/','https://meet.new/']){
   const p=await c.newPage();
   try{
     const failures=[];
     p.on('requestfailed',r=>{if(failures.length<6)failures.push({host:new URL(r.url()).hostname,type:r.failure()?.slice(0,70)})});
     await p.goto(endpoint,{waitUntil:'domcontentloaded',timeout:45000}).catch(e=>console.log('QA_PAGE_NAVIGATION_ERROR_CLASS',e.name));
     await p.waitForTimeout(4500);
     const info=await p.evaluate(()=>{
       const controls=Array.from(document.querySelectorAll('button,[role="button"],[role="menuitem"],input'))
         .slice(0,75).map(e=>({role:e.getAttribute('role')||e.tagName.toLowerCase(),
           text:String(e.getAttribute('aria-label')||e.getAttribute('placeholder')||e.textContent||'').trim().replace(/\s+/g,' ').slice(0,65)}))
         .filter(x=>x.text.length>0);
       const labels=controls.filter(x=>/new meet|meeting|create|start|join|later|sign in|login|meet|besprechung|teilnehm|später|jetzt|ورود|جلسه/i.test(x.text)).slice(0,20);
       return {ready:document.readyState,buttonCount:document.querySelectorAll('button').length,
         htmlLength:document.documentElement?.outerHTML.length||0,
         bodyLength:document.body?.innerText.length||0,
         hasIframe:document.querySelectorAll('iframe').length,
         language:document.documentElement?.lang||null,
         controls:labels};
     });
     const u=new URL(p.url());
     console.log('QA_MEET_PAGE',endpoint.includes('meet.new')?'instant':'landing',
       JSON.stringify({urlHost:u.hostname,urlPathIsRoot:u.pathname==='/',isMeetRoom:/^\/[a-z]{3}-[a-z]{4}-[a-z]{3}/.test(u.pathname),
         loginRedirect:u.hostname.includes('accounts.google.com'),...info,requestErrors:failures}));
   }finally{await p.close().catch(()=>{})}
 }
 await b.close().catch(()=>{});
})().catch(e=>{console.error('QA_MEET_PAGE_DIAG_ERROR',e.name);process.exitCode=2;});