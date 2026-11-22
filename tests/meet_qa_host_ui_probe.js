/* Disposable Meet host UI probe; no inviting others, no recording. */
'use strict';
const {chromium}=require('playwright');
(async()=>{
 const b=await chromium.connectOverCDP('http://beonmeet-isolated-chrome-3:9223',{timeout:17000});
 let p;
 try{
  const c=b.contexts()[0];
  p=await c.newPage();
  await p.goto('https://meet.new/',{waitUntil:'domcontentloaded',timeout:50000});
  await p.waitForTimeout(3500);
  const text=await p.evaluate(()=>{
   const list=Array.from(document.querySelectorAll('button,[role="button"]'));
   const patterns=/join|start|leave|microphone|camera|mute|call|meeting|now|jetzt|teilnehm|anruf|میکروفون|پیوست|خروج|دوربین/i;
   return list.map(e=>(e.getAttribute('aria-label')||e.innerText||'').trim().replace(/\s+/g,' '))
       .filter(s=>s&&s.length<90&&patterns.test(s)).slice(0,25);
  });
  const real=/^https:\/\/meet\.google\.com\/[a-z]{3}-[a-z]{4}-[a-z]{3}/.test(p.url());
  console.log('MEET_HOST_PROBE_ON_VALID_MEET_CODE',real);
  console.log('MEET_HOST_PROBE_BUTTONS',JSON.stringify(text));
  console.log('MEET_HOST_PROBE_HAS_IN_CALL_UI',text.some(x=>/leave call|anruf verlassen/i.test(x)));
  console.log('MEET_HOST_PROBE_HAS_PREJOIN_BUTTON',text.some(x=>/join now|jetzt teilnehmen|ask to join|teilnahme erbitten/i.test(x)));
 } finally{if(p)await p.close().catch(()=>{});await b.close().catch(()=>{});}
})().catch(e=>{console.error('MEET_HOST_PROBE_ERROR_CLASS',e.name);process.exitCode=2;});
