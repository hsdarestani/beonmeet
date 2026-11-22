'use strict';
/* Direct Google Meet diagnostics without changing login state or exposing IDs.
 * Compare My Account (the page shown by owner), Meet landing and actual
 * meeting URL navigation with one existing QA link. No joins or clicks.
 */
const {chromium}=require('playwright');
function category(url){
 try{
  const u=new URL(url);
  if(u.hostname==='myaccount.google.com')return 'account-dashboard';
  if(u.hostname==='accounts.google.com')return 'login-or-consent';
  if(u.hostname==='workspace.google.com')return 'workspace-marketing';
  if(u.hostname==='meet.google.com'){
   if(/^\/[a-z]{3}-[a-z]{4}-[a-z]{3}/i.test(u.pathname))return 'meet-room';
   return 'meet-landing';
  }
  return u.hostname.replace(/[^a-z0-9.-]/ig,'').slice(0,60);
 }catch(e){return 'invalid-url'}
}
(async()=>{
 const browser=await chromium.connectOverCDP('http://beonmeet-chrome-single:9223',{timeout:15000});
 let qaCode=null;
 try{
  const ctx=browser.contexts()[0];
  if(!ctx)throw Error('no-persistent-context');
  for(let i=0;i<3;i++){
   let label,uri;
   if(i===0){label='Google account';uri='https://myaccount.google.com/'}
   if(i===1){label='Meet home';uri='https://meet.google.com/'}
   if(i===2){
    label='Meet existing QA room';
    const fs=require('fs');
    const file='/qa-existing-links.json';
    if(!fs.existsSync(file)){console.log('MEET_DIRECT_QA_ROOM_FILE_ABSENT');continue}
    const urls=JSON.parse(fs.readFileSync(file,'utf8')).links;
    if(!urls?.[0]||!/^https:\/\/meet\.google\.com\/[a-z]{3}-[a-z]{4}-[a-z]{3}$/.test(urls[0]))
      throw Error('Invalid test room metadata');
    uri=urls[0];
   }
   const p=await ctx.newPage();
   try{
    const visited=[];
    p.on('framenavigated',f=>{
      if(f===p.mainFrame()&&visited.length<10)visited.push(category(f.url()));
    });
    let topStatus=null;
    let navError=null;
    try{
      const response=await p.goto(uri,{waitUntil:'domcontentloaded',timeout:40000});
      topStatus=response?.status()||null;
    }catch(e){navError=e.name}
    await p.waitForTimeout(1800);
    const final=category(p.url());
    const ui=await p.evaluate(()=>{
      const buttons=Array.from(document.querySelectorAll('button,[role=button]'));
      const text=buttons.map(b=>String(b.getAttribute('aria-label')||b.textContent||'').trim().toLowerCase());
      const match=(...needles)=>text.some(s=>needles.some(n=>s.includes(n)));
      return {
        buttonCount:buttons.length,
        meetingJoinButton:match('join now','ask to join','teilnahme erbitten','jetzt teilnehmen'),
        inCallButton:match('leave call','anruf verlassen'),
        meetingCreateButton:match('new meeting','neue besprechung'),
        loginButton:match('sign in','anmelden'),
        bodyHasContent:!!document.body?.innerText?.trim(),
        titleIsGoogleAccount:/google account/i.test(document.title),
        titleIsGoogleMeet:/meet/i.test(document.title),
      }
    });
    console.log('MEET_DIRECT_BROWSER_RESULT',JSON.stringify({page:label,final,topStatus,navError,visited,ui}));
   }finally{await p.close().catch(()=>{})}
  }
 }finally{await browser.close().catch(()=>{})}
})().catch(e=>{console.log('MEET_DIRECT_DIAGNOSTIC_FAILED',e.name);process.exitCode=2});
