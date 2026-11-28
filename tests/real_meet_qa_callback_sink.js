/* Private QA-only callback sink for real Google Meet join/recording canary.
 * No Telegram messages, billing or customer data. Docker-private network only.
 * Saves ONLY qa_lane_2 stream to a scratch directory for ffprobe verification.
 */
'use strict';
const http=require('http'),fs=require('fs'),path=require('path');
fs.mkdirSync('/qa',{recursive:true});
let start=0, waiting=0, uploaded=0;
function note(type){
 fs.appendFileSync('/qa/status.jsonl',JSON.stringify({type,at:Date.now()})+'\n');
}
function done(res,code,data){
 res.writeHead(code,{'content-type':'application/json'});
 res.end(JSON.stringify(data||{ok:code===200}));
}
http.createServer((req,res)=>{
 try{
 if(req.method==='GET'&&req.url==='/health'){
   return done(res,200,{ok:true,start,waiting,uploaded});
 }
 if(req.method!=='POST')return done(res,405,{ok:false});
 const url=req.url||'';
 if(url.includes('recording-started')){
   start++;note('recording_started');req.resume();return done(res,200,{ok:true,recording_limit_seconds:null});
 }
 if(url.includes('waiting-for-admission')){
   waiting++;note('waiting_for_admission');req.resume();return done(res,200);
 }
 if(!url.includes('recording-ready')&&!url.includes('recording-upload')){
   req.resume();return done(res,404,{ok:false});
 }
 const target='/qa/qa-lane-2-recording.webm';
 if(String(req.headers['content-type']||'').startsWith('application/octet-stream')){
   const metaHeader=req.headers['x-beonmeet-meta'];
   if(!metaHeader)return done(res,400,{ok:false});
   const meta=JSON.parse(Buffer.from(String(metaHeader),'base64url').toString('utf8'));
   if(meta.userId!=='qa_lane_2')return done(res,403,{ok:false});
   let length=0;
   const fd=fs.createWriteStream(target,{flags:'wx'});
   req.on('data',buf=>{length+=buf.length;if(length>350*1024*1024)req.destroy();});
   req.pipe(fd);
   fd.on('finish',()=>{uploaded++;note('recording_uploaded');done(res,200,{ok:true,persisted:true});});
   fd.on('error',()=>{if(!res.headersSent)done(res,500,{ok:false});});
   return;
 }
 let body='';
 req.setEncoding('utf8');
 req.on('data',chunk=>{body+=chunk;if(body.length>15000)req.destroy();});
 req.on('end',()=>{
   try{
     const data=JSON.parse(body);
     if(data.userId!=='qa_lane_2')return done(res,403,{ok:false});
     const source=path.resolve(String(data.filePath||''));
     if(!source.startsWith('/recordings/qa_lane_2/'))return done(res,403,{ok:false});
     fs.copyFileSync(source,target,fs.constants.COPYFILE_EXCL);
     uploaded++;note('recording_uploaded');return done(res,200,{ok:true,persisted:true});
   }catch(e){return done(res,500,{ok:false});}
 });
 }catch(e){
   if(!res.headersSent)done(res,500,{ok:false});
 }
}).listen(3030,'0.0.0.0',()=>{console.log('QA_CALLBACK_SINK_LISTENING');});
