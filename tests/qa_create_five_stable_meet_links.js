/* Create private, noninstant Google Meet QA links using "Create meeting for later".
 * This avoids relying on meet.new rooms that may expire after all leave.
 * Requires valid signed-in profile. Prints only one machine JSON to be redirected
 * to a private root-owned file on the server. Never sends invitations.
 */
'use strict';
const {chromium}=require('playwright');
const LINK=/https:\/\/meet\.google\.com\/[a-z]{3}-[a-z]{4}-[a-z]{3}/ig;
async function clickOne(page,options,label){
 for(const selector of options){
  try{
   const control=page.getByRole('button',{name:selector}).first();
   if(await control.isVisible({timeout:1500})){await control.click({timeout:7000});return;}
  }catch(e){}
  try{
   const item=page.getByRole('menuitem',{name:selector}).first();
   if(await item.isVisible({timeout:1000})){await item.click({timeout:7000});return;}
  }catch(e){}
 }
 throw Error('Could not find '+label+' control in authenticated Meet UI');
}
(async()=>{
 const b=await chromium.connectOverCDP('http://beonmeet-chrome-single:9223',{timeout:12000});
 try{
  const c=b.contexts()[0];if(!c)throw Error('Authenticated Chrome context missing');
  const p=await c.newPage();
  const links=[];
  try{
   await p.goto('https://meet.google.com/?hl=en',{waitUntil:'domcontentloaded',timeout:40000});
   await p.waitForTimeout(1500);
   if(new URL(p.url()).hostname!=='meet.google.com')
     throw Error('GOOGLE_MEET_SIGN_IN_REQUIRED: landing page redirected');
   for(let n=0;n<5;n++){
    await clickOne(p,[/New meeting/i,/Neue Besprechung/i,/Nouvelle réunion/i,/جلسه جدید/],'New meeting');
    await p.waitForTimeout(250);
    await clickOne(p,[/Create a meeting for later/i,/Besprechung für später/i,/Créer une réunion pour plus tard/i,/ایجاد.*بعد/],'Create for later');
    await p.waitForTimeout(650);
    const candidate=await p.evaluate(()=>{
     const strings=[document.body?.innerText||''];
     for(const e of document.querySelectorAll('input,[role=dialog],a[href*="meet.google.com"]')){
       strings.push(String(e.value||''));
       strings.push(String(e.getAttribute('href')||''));
       strings.push(String(e.innerText||''));
     }
     return strings.join('\n');
    });
    const match=candidate.match(LINK);
    if(!match||!match.length)throw Error('Create for later did not return a test link');
    const uri=match[0].toLowerCase();
    if(links.includes(uri))throw Error('Duplicate meeting code');
    links.push(uri);
    await p.keyboard.press('Escape');
    await p.waitForTimeout(300);
    if(n<4 && !await p.getByRole('button',{name:/New meeting|Neue Besprechung|Nouvelle réunion|جلسه جدید/i}).first().isVisible({timeout:800}).catch(()=>false)){
      await p.goto('https://meet.google.com/?hl=en',{waitUntil:'domcontentloaded',timeout:35000});
    }
   }
   if(links.length!==5)throw Error('Did not obtain five unique stable links');
   process.stdout.write(JSON.stringify({source:'create-for-later',links})+'\n');
  }finally{await p.close().catch(()=>{})}
 }finally{await b.close().catch(()=>{})}
})().catch(e=>{console.error('STABLE_MEET_LINK_CREATION_FAILED',e.message.split(':')[0].slice(0,100));process.exitCode=2;});