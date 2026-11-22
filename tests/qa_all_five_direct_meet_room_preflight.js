'use strict';
/* Read-only test of each isolated Chrome against one of five private QA Meet
   URLs. No meeting codes, personal data, account names or cookie values logged.
 */
const {chromium}=require('playwright'),fs=require('fs');
function where(url){
 const u=new URL(url);
 if(u.hostname==='meet.google.com')return /^\/[a-z]{3}-[a-z]{4}-[a-z]{3}/i.test(u.pathname)?'room':'landing';
 if(u.hostname==='accounts.google.com')return 'sign-in-page';
 if(u.hostname==='workspace.google.com')return 'marketing';
 return 'other-domain';
}
(async()=>{
 const links=JSON.parse(fs.readFileSync('/qa-existing-links.json','utf8')).links;
 if(!Array.isArray(links)||links.length!==5)throw Error('test-link-list-invalid');
 for(let i=0;i<5;i++){
  const lane=i===0?'original':String(i+1);
  const host=i===0?'beonmeet-chrome-single':'beonmeet-isolated-chrome-'+(i+1);
  const b=await chromium.connectOverCDP('http://'+host+':9223',{timeout:14000});
  try{
   const ctx=b.contexts()[0];if(!ctx)throw Error('no-context');
   const p=await ctx.newPage();
   try{
    const visited=[];
    p.on('framenavigated',f=>{if(f===p.mainFrame()&&visited.length<8)visited.push(where(f.url()))});
    const res=await p.goto(links[i],{waitUntil:'domcontentloaded',timeout:45000});
    await p.waitForTimeout(1700);
    const ui=await p.evaluate(()=>{
      const texts=Array.from(document.querySelectorAll('button,[role=button]'))
        .map(e=>String(e.getAttribute('aria-label')||e.textContent||'').trim().toLowerCase());
      const match=(...words)=>texts.some(s=>words.some(w=>s.includes(w)));
      const body=String(document.body?.innerText||'').toLowerCase();
      return {
        buttons:texts.length,
        joinNow:match('join now','jetzt teilnehmen','rejoindre','پیوستن'),
        askToJoin:match('ask to join','teilnahme erbitten','demander à participer','درخواست پیوستن'),
        leaveCall:match('leave call','anruf verlassen','quitter l’appel'),
        signIn:match('sign in','anmelden','se connecter','ورود'),
        expired:/meeting (does not exist|not found|has ended)|besprechung existiert nicht|this meeting is no longer|invalid meeting/.test(body),
        create:match('new meeting','neue besprechung'),
        hasMediaUi:match('microphone','camera','mikrofon','kamera','micro','caméra')
      };
    });
    console.log('MEET_QA_LANE_PREFLIGHT',JSON.stringify({lane,final:where(p.url()),status:res?.status()||0,visited,ui}));
   }finally{await p.close().catch(()=>{})}
  }finally{await b.close().catch(()=>{})}
 }
})().catch(e=>{console.log('MEET_QA_LANE_PREFLIGHT_FAILED',e.code||e.name);process.exitCode=2});
