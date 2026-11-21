/* Five independent ephemeral Chrome CDP containers, with one MediaRecorder each.
   This is NOT a test of Google Meet join, consent, or Telegram delivery.
   Requires playwright already installed in the BeOnMeet worker container.
   No existing Chrome login/profile or customer recordings are accessed. */
'use strict';
const fs = require('fs');
const {chromium} = require('playwright');
const SECONDS = Math.max(30, Math.min(600, Number(process.env.QA_SECONDS) || 180));
const OUTDIR = process.env.QA_OUTDIR || '/tmp/beonmeet-five-sustained-20261121';
if(!OUTDIR.startsWith('/tmp/beonmeet-five-')) throw Error('QA output must remain in test-only /tmp directory');
const WIDTH = Math.max(640, Math.min(1280, Number(process.env.QA_WIDTH) || 640));
const HEIGHT = Math.max(360, Math.min(720, Number(process.env.QA_HEIGHT) || 360));
const FPS = Math.max(5, Math.min(15, Number(process.env.QA_FPS) || 8));
const VIDEO_BPS = Math.max(200000, Math.min(1500000, Number(process.env.QA_VIDEO_BPS) || 320000));
const AUDIO_BPS = Math.max(48000, Math.min(128000, Number(process.env.QA_AUDIO_BPS) || 64000));
const CDP_URLS = [1,2,3,4,5].map(i=>`http://beonmeet-five-qa-chrome-${i}:9223`);
const RATES = [220,330,440,550,660];
fs.mkdirSync(OUTDIR, {recursive:false});
const paths = RATES.map((_,i)=>OUTDIR+'/stream-'+(i+1)+'.webm');
const received = RATES.map(()=>({bytes:0,chunks:0,writeErrors:0}));
let browsers=[], pages=[];
const startedAt=Date.now();

async function main() {
  console.log('QA_AV_START '+JSON.stringify({seconds:SECONDS,width:WIDTH,height:HEIGHT,fps:FPS,videoBits:VIDEO_BPS,audioBits:AUDIO_BPS,output:OUTDIR}));
  for (let i=0; i<5; i++) {
    const browser = await chromium.connectOverCDP(CDP_URLS[i], {timeout:12000});
    browsers.push(browser);
    const ctx=browser.contexts()[0] || await browser.newContext();
    const p=await ctx.newPage();
    pages.push(p);
    await p.exposeFunction('qaSendChunk',async (index, b64)=>{
      if(index!==i) throw Error('Wrong recording stream ID');
      const buf=Buffer.from(b64,'base64');
      fs.appendFileSync(paths[index],buf);
      received[index].bytes+=buf.length;
      received[index].chunks++;
    });
    const res=await p.evaluate(async ({index, tone, width, height, fps, videoBps, audioBps})=>{
      let canvas=document.createElement('canvas');
      canvas.width=width;canvas.height=height;document.body.appendChild(canvas);
      const g=canvas.getContext('2d',{alpha:false});
      const video=canvas.captureStream(fps);
      const audioContext=new AudioContext({sampleRate:48000});
      const sine=audioContext.createOscillator();
      sine.type='sine';sine.frequency.value=tone;
      const gain=audioContext.createGain();gain.gain.value=0.06;
      const out=audioContext.createMediaStreamDestination();
      sine.connect(gain);gain.connect(out);sine.start();
      await audioContext.resume();
      const tracks=[...video.getVideoTracks(), ...out.stream.getAudioTracks()];
      if(tracks.length!==2 || audioContext.state!=='running') throw Error('Audio or video not available');
      const stream=new MediaStream(tracks);
      const mime=['video/webm;codecs=vp8,opus','video/webm;codecs=vp8','video/webm'].find(s=>MediaRecorder.isTypeSupported(s));
      if(!mime)throw Error('VP8 MediaRecorder codec missing');
      const rec=new MediaRecorder(stream,{mimeType:mime,videoBitsPerSecond:videoBps,audioBitsPerSecond:audioBps});
      let frames=0, errors=0, chunksSent=0;
      let upload=Promise.resolve();
      const t0=performance.now();
      const draw=()=>{
        g.fillStyle='hsl('+(index*64+frames%360)+',52%,24%)';
        g.fillRect(0,0,width,height);
        const x=(frames*5) % (width-85);
        g.fillStyle='white';
        g.fillRect(x,100,85,95);
        g.fillStyle='hsl('+(index*64)+',90%,57%)';
        g.font='bold 30px sans-serif';
        g.fillText('QA STREAM '+(index+1),24,55);
        g.font='18px sans-serif';
        g.fillText('frame '+frames+' / tone '+tone+' Hz',24,height-35);
        frames++;
      };
      draw();
      const drawTimer=setInterval(draw,Math.round(1000/fps));
      rec.onerror=e=>{errors++;console.error('QA recorder error '+index,e.error && e.error.message)};
      rec.ondataavailable=(e)=>{
        if(e.data.size===0){errors++;return;}
        upload=upload.then(async()=>{
          const buf=new Uint8Array(await e.data.arrayBuffer());
          let result='';
          for(let offset=0;offset<buf.length;offset+=8192){
            result += String.fromCharCode(...buf.slice(offset,offset+8192));
          }
          await window.qaSendChunk(index,btoa(result));
          chunksSent++;
        }).catch(e=>{errors++;console.error('QA upload error '+index,e.message)});
      };
      const stopped=new Promise(resolve=>{rec.onstop=resolve});
      rec.start(2000);
      window.__qa={frames:()=>frames,t0,stop:async()=>{
        if(rec.state!=='inactive')rec.stop();
        await Promise.race([stopped,new Promise((_,reject)=>setTimeout(()=>reject(Error('MediaRecorder stop timeout')),30000))]);
        await upload;
        clearInterval(drawTimer);
        stream.getTracks().forEach(t=>t.stop());
        sine.stop();await audioContext.close();
        return {index,tone,frames,errors,chunksSent,
          durationSeconds:Math.round((performance.now()-t0)/1000),
          audioTracks:out.stream.getAudioTracks().length,
          videoTracks:video.getVideoTracks().length,
          codec:rec.mimeType};
      }};
      return {index,tone,codec:rec.mimeType,contextState:audioContext.state};
    },{index:i,tone:RATES[i],width:WIDTH,height:HEIGHT,fps:FPS,videoBps:VIDEO_BPS,audioBps:AUDIO_BPS});
    console.log('QA_AV_PAGE_READY '+JSON.stringify(res));
  }
  console.log('QA_ALL_FIVE_RECORDERS_STARTED');
  const progress = setInterval(async()=>{
    try {
      const vals=await Promise.all(pages.map(p=>p.evaluate(()=>({frames:window.__qa.frames()}))));
      console.log('QA_PROGRESS '+JSON.stringify({elapsed:Math.round((Date.now()-startedAt)/1000),
        frames:vals.map(x=>x.frames),bytes:received.map(x=>x.bytes)}));
    }catch(e){ console.log('QA_PROGRESS_ERROR '+e.message); }
  },30000);
  await new Promise((resolve,reject)=>{
    const timeout=setTimeout(()=>{clearInterval(checker);resolve();},SECONDS*1000);
    const checker=setInterval(()=>{
      if(fs.existsSync('/tmp/beonmeet-five-sustained-abort-20261119')){
        clearTimeout(timeout);clearInterval(checker);
        reject(Error('Host health guard requested abort'));
      }
    },2000);
  });
  clearInterval(progress);
  const results=await Promise.all(pages.map(p=>p.evaluate(()=>window.__qa.stop())));
  console.log('QA_RECORDER_INTERNAL_META '+JSON.stringify(results));
  const stats=results.map((v,i)=>({...v,
    bytes:fs.existsSync(paths[i])?fs.statSync(paths[i]).size:0,
    receivedChunks:received[i].chunks}));
  console.log('QA_AV_RESULTS '+JSON.stringify(stats));
  const fail=stats.filter(v=>v.errors||v.frames<SECONDS*Math.max(4,Math.floor(FPS*.55))||
    v.durationSeconds<SECONDS-5||v.bytes<SECONDS*1200||v.receivedChunks<SECONDS/5||
    v.audioTracks!==1||v.videoTracks!==1);
  if(fail.length) throw Error('Recording assertions failed for '+fail.map(x=>x.index).join(','));
  console.log('QA_FIVE_ISOLATED_CHROME_AV_STREAMS_PASS');
}
main().catch(e=>{console.error('QA_FIVE_AV_STREAMS_FAILED '+(e && e.stack||e));process.exitCode=2})
  .finally(async()=>{
    for(const p of pages)await Promise.race([p.close().catch(()=>{}),new Promise(resolve=>setTimeout(resolve,2500))]);
    for(const b of browsers)await Promise.race([b.close().catch(()=>{}),new Promise(resolve=>setTimeout(resolve,2500))]);
  });
