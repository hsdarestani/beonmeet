'use strict';
/* Probe what Google's Meet "Sign in" control does when the Chrome profile
 * already displays signed-in Google Account. Only on one owned QA room.
 * Do not type credentials, choose accounts, click Join or log private content.
 */
const {chromium}=require('playwright'),fs=require('fs');
function kind(url){
 const u=new URL(url);
 if(u.hostname==='meet.google.com')return /^\/[a-z]{3}-[a-z]{4}-[a-z]{3}/i.test(u.pathname)?'meet-prejoin':'meet-home';
 if(u.hostname==='accounts.google.com')return 'google-account-login-flow';
 if(u.hostname==='workspace.google.com')return 'workspace-marketing';
 if(u.hostname==='myaccount.google.com')return 'google-account-dashboard';
 return 'another-page';
}
(async()=>{
 const links=JSON.parse(fs.readFileSync('/qa-existing-links.json','utf8')).links;
 const b=await chromium.connectOverCDP('http://beonmeet-chrome-single:9223',{timeout:14000});
 try{
  const c=b.contexts()[0],p=await c.newPage();
  try{
   await p.goto(links[0],{waitUntil:'domcontentloaded',timeout:40000});
   await p.waitForTimeout(1200);
   const before=kind(p.url());
   const signin=p.getByRole('button',{name:/^Sign in$|^Anmelden$|^Se connecter$|^ورود$/i}).first();
   const visible=await signin.isVisible({timeout:1300}).catch(()=>false);
   console.log('MEET_SIGNIN_CONTROL_PRECHECK',JSON.stringify({before,visible}));
   if(!visible){console.log('MEET_SIGNIN_CONTROL_NOT_PRESENT');return}
   await signin.click({timeout:7000});
   await p.waitForTimeout(2500);
   const current=kind(p.url());
   const state=await p.evaluate(()=>{
     const inputs=Array.from(document.querySelectorAll('input'));
     const passwordVisible=inputs.some(x=>x.type==='password'&&x.offsetParent!==null);
     const emailVisible=inputs.some(x=>x.type==='email'&&x.offsetParent!==null);
     const text=String(document.body?.innerText||'').toLowerCase();
     return {
       passwordPrompt:passwordVisible,
       emailPrompt:emailVisible,
       chooseAccount:text.includes('choose an account')||text.includes('konto auswählen')||text.includes('choisir un compte'),
       tryAnotherWay:text.includes('try another way'),
       joinControls:!!document.querySelector('button'),
       securityChallenge:text.includes('verify it')||text.includes('2-step verification')
     };
   });
   console.log('MEET_SIGNIN_CONTROL_AFTER',JSON.stringify({from:before,to:current,...state}));
  }finally{await p.close().catch(()=>{})}
 }finally{await b.close().catch(()=>{})}
})().catch(e=>{console.log('MEET_SIGNIN_CONTROL_PROBE_FAILED',e.code||e.name);process.exitCode=2});
