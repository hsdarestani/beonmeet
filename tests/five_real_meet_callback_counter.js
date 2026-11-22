/* Private callback counter for five real Google Meet test sessions.
   Accepts only qa_lane_[2-6] events. NEVER sends to production controller.
   No customer uploads, Telegram messages, billing, or credential logging.
*/
'use strict';
const http=require('http'),fs=require('fs');
const started=new Set(),waiting=new Set(),uploaded=new Set();
const idre=/^qa_lane_[2-6]$/;
function reply(res,code,payload){
  res.writeHead(code,{'content-type':'application/json'});
  res.end(JSON.stringify(payload||{ok:code===200}));
}
function acceptId(payload){
  const id=String(payload&&payload.userId||'');
  return idre.test(id)?id:null;
}
http.createServer((req,res)=>{
  if(req.method==='GET'&&req.url==='/health')
    return reply(res,200,{ok:true,started:[...started],waiting:[...waiting],uploaded:[...uploaded]});
  if(req.method!=='POST')return reply(res,405);
  const name=String(req.url||'');
  const isUpload=/recording-(ready|upload)/.test(name);
  const isStart=name.includes('recording-started');
  const isWait=name.includes('waiting-for-admission');
  if(!isUpload&&!isStart&&!isWait)return reply(res,404);
  if(isUpload&&String(req.headers['content-type']||'').startsWith('application/octet-stream')){
    try{
      const meta=JSON.parse(Buffer.from(String(req.headers['x-beonmeet-meta']||''),'base64url').toString());
      const id=acceptId(meta);
      if(!id)return reply(res,403);
      let count=0;
      req.on('data',v=>{count+=v.length;if(count>450*1024*1024)req.destroy()});
      req.on('end',()=>{uploaded.add(id);reply(res,200)});
      return;
    }catch(e){return reply(res,400);}
  }
  let text='';
  req.on('data',v=>{text+=v.toString();if(text.length>20000)req.destroy()});
  req.on('end',()=>{
    try{
      const data=JSON.parse(text||'{}');
      const id=acceptId(data);
      if(!id)return reply(res,403);
      if(isStart)started.add(id);
      else if(isWait)waiting.add(id);
      else uploaded.add(id);
      reply(res,200);
    }catch(e){reply(res,400);}
  });
}).listen(3031,'0.0.0.0',()=>console.log('FIVE_REAL_MEET_QA_SINK_READY'));
