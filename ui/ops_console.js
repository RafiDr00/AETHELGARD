import { apiGet, apiPost, ensureApiKey, getApiKey, getApiBaseUrl } from '/modules/api_client.js';
import { createSparkHistory, clamp, updateMetric, pushHistory, renderSparks } from '/modules/metrics.js';

function tick(){
  const n=new Date();
  const hms=[n.getHours(),n.getMinutes(),n.getSeconds()].map(x=>String(x).padStart(2,'0')).join(':');
  document.getElementById('clock').innerHTML=hms+'<span class="ms">.'+String(n.getMilliseconds()).padStart(3,'0')+'</span>';
}
setInterval(tick,50);tick();

const streamEl=document.getElementById('stream');
const reasoningEl=document.getElementById('reasoning');
const resolutionsEl=document.getElementById('resolutions');
let eventCount=0;
const sparkHistory=createSparkHistory();

function nowTs(){
  const n=new Date();
  return [n.getHours(),n.getMinutes(),n.getSeconds()].map(x=>String(x).padStart(2,'0')).join(':');
}

function toast(msg){
  const t=document.getElementById('toast');
  t.textContent=msg;
  t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'),3200);
}

function severityTag(sev){
  if(sev==='error')return 'ERR';
  if(sev==='warning')return 'WRN';
  if(sev==='success')return 'OK';
  if(sev==='trigger')return 'TRG';
  return 'INF';
}

function eventClassBySeverity(sev){
  if(sev==='error')return 'anomaly';
  if(sev==='success')return 'success';
  if(sev==='warning')return 'trigger';
  return '';
}

function addEventRow({ts,tag,msg,cls}){
  const d=document.createElement('div');
  d.className=`ev ${cls||''}`;
  const tc={'ERR':'t-e','OK':'t-s','TRG':'t-w','INF':'t-i','WRN':'t-w'}[tag]||'t-i';
  d.innerHTML=`<span class="ev-ts">${ts}</span><span class="ev-tag ${tc}">${tag}</span><span class="ev-msg">${msg}</span>`;
  streamEl.prepend(d);
  while(streamEl.children.length>120){streamEl.removeChild(streamEl.lastChild);}  
  eventCount+=1;
  document.getElementById('ev-cnt').textContent=String(eventCount).padStart(3,'0')+' EVENTS';
}

function typewrite(el, text, cb) {
  let i=0;
  const tw=document.createElement('span');
  const cur=document.createElement('span');cur.className='cursor-b';
  el.appendChild(tw);el.appendChild(cur);
  function tick(){
    if(i<text.length){
      tw.textContent+=text[i++];
      setTimeout(tick, i<4?50:i<12?22:10);
    } else {
      cur.remove();
      if(cb) setTimeout(cb,700);
    }
  }
  tick();
}

function addReasoning(type,label,text,ts=nowTs()){
  const b=document.createElement('div');
  b.className=`rb ${type}`;
  b.innerHTML=`<div class="rb-head"><span class="rb-ts">${ts}</span><span class="rb-type">${label}</span></div><div class="rb-txt"></div>`;
  reasoningEl.prepend(b);
  const tx=b.querySelector('.rb-txt');
  typewrite(tx, text);
  while(reasoningEl.children.length>5){reasoningEl.removeChild(reasoningEl.lastChild);}  
}

function setNode(idx,state,top1,top2,bottom,duration){
  const node=document.getElementById(`n${idx}`);
  const label=document.getElementById(`l${idx}`);
  const vA=document.getElementById(`v${idx}a`);
  const vB=document.getElementById(`v${idx}b`);
  const t=document.getElementById(`t${idx}`);
  const nd=document.getElementById(`nd${idx}`);
  if(!node)return;

  node.className=`node ${state}`;
  if(label){
    if(state==='success'){label.style.color='var(--ok)';}
    else if(state==='running'){label.style.color='var(--p)';}
    else if(state==='fail'){label.style.color='var(--err)';}
    else{label.style.color='var(--t2)';}
  }

  if(vA) vA.textContent=top1||'—';
  if(vB) vB.textContent=top2||'—';
  if(t)  t.textContent=bottom||'—';
  if(nd) nd.textContent=duration||'—';

  const cl=(state==='running'?' live':state==='success'?' done':'');
  if(vA) vA.className='nd-v'+cl;
  if(vB) vB.className='nd-v'+cl;
  if(t)  t.className='nd-v'+cl;
}

function setProgress(pct,status){
  document.getElementById('pp-fill').style.width=`${pct}%`;
  document.getElementById('pp-pct').textContent=`${Math.round(pct)}%`;
  document.getElementById('pp-status').textContent=status;
}

let lastJobId='';

function applyOpsSnapshot({health,ops,jobsResp,timeline,spans}){
  document.getElementById('state-indicator').textContent=`● ${String(health?.status||'degraded').toUpperCase()}`;
  document.getElementById('gateway').textContent=health?.status==='healthy'?'OK':'WARN';

  const consistency=clamp(99-(Number(ops?.failedHealth||0)*0.8),70,99.9);
  const precision=clamp(Number(ops?.autonomousResolutionRate||0),0,100);
  const mttd=Number(ops?.mttdSeconds||0);
  const mttr=Number(ops?.mttrSeconds||0);
  const iph=clamp(Number(ops?.activePipelines||0)*0.2,0,2);

  updateMetric('m1','b1',consistency,100,1);
  updateMetric('m2','b2',precision,100,1);
  updateMetric('m3','b3',mttd,10,1);
  updateMetric('m4','b4',mttr,20,1);
  updateMetric('m5','b5',iph,2,2);

  pushHistory(sparkHistory,'m1',consistency);
  pushHistory(sparkHistory,'m2',precision);
  pushHistory(sparkHistory,'m3',mttd);
  pushHistory(sparkHistory,'m4',mttr);
  pushHistory(sparkHistory,'m5',iph);
  renderSparks(sparkHistory);

  const agents=Math.max(Number(health?.agents_active||0),0);
  document.getElementById('wc').textContent=`${Math.min(agents,8)}/8`;
  document.getElementById('groups').textContent=String(Math.max(1, Number(ops?.activePipelines||0) + 1));

  const jobs=(jobsResp?.jobs||[]);
  const latest=jobs[0]||null;

  resolutionsEl.innerHTML='';
  jobs.slice(0,5).forEach(j=>{
    const row=document.createElement('div');
    row.className='ml-row';
    const tm=(j.updated_at||j.created_at||new Date().toISOString()).slice(11,19);
    const status=(j.status||'').toLowerCase();
    const cls=status==='completed'?'ok':status==='failed'?'err':'';
    row.innerHTML=`<span class="ml-t">${tm}</span><span class="ml-v ${cls}">${j.job_id} · ${status.toUpperCase()}${j.mttr_seconds?` · MTTR ${j.mttr_seconds}s`:''}</span>`;
    resolutionsEl.appendChild(row);
  });

  if(!latest){
    document.getElementById('pipe-badge').textContent='STANDBY';
    setProgress(0,'STANDBY');
    for(let i=0;i<5;i++)setNode(i,'idle','awaiting signal','—','—','idle');
    return;
  }

  document.getElementById('pipe-badge').textContent=`${(latest.status||'pending').toUpperCase()} · ${latest.job_id}`;
  if(latest.job_id!==lastJobId){
    lastJobId=latest.job_id;
    addReasoning('thought','THOUGHT',`Tracking pipeline job ${latest.job_id} (${latest.scenario||'scenario unknown'}).`);
  }

  const stageOrder=['detection','diagnosis','remediation','validation','deployment'];
  const timelineMap=new Map((timeline?.timeline||[]).map(s=>[s.stage,s]));
  const spansMap=new Map((spans?.spans||[]).map(s=>[(s.name||'').replace('agent.',''),s]));

  let done=0;
  let hasRunning=false;

  stageOrder.forEach((stage,idx)=>{
    const t=timelineMap.get(stage);
    const sp=spansMap.get(stage);
    const stat=(t?.status||'pending').toLowerCase();
    const det=t?.details || sp?.details || 'pending';
    const duration=sp?.duration?`${(sp.duration/1000).toFixed(1)}s`:(stat==='success'?'✓':'idle');

    let nodeState='idle';
    if(stat==='success'){nodeState='success';done++;}
    else if(stat==='running'){nodeState='running';hasRunning=true;}
    else if(stat==='failed' || stat==='rolled_back'){nodeState='fail';}

    const topMain=(det||'—').slice(0,26);
    const topSub=(sp?.attributes?.service_name || latest.service || 'orchestrator').slice(0,22);
    const bottom=stat==='success'?'✓ complete':stat==='running'?'active':stat==='failed'?'failed':'—';
    setNode(idx,nodeState,topMain,topSub,bottom,duration);
  });

  let progress=done*20;
  if(hasRunning)progress=Math.min(progress+10,95);
  if((latest.status||'').toLowerCase()==='completed')progress=100;
  if((latest.status||'').toLowerCase()==='failed')progress=Math.max(progress,40);

  setProgress(progress,(latest.status||'pending').toUpperCase());

  const tl=(timeline?.timeline||[]).slice(-4);
  const typeMap=['thought','action','obs','decision'];
  tl.forEach((step,i)=>{
    if(!step?.details)return;
    const tag=(step.status||'').toLowerCase();
    // Force some visual diversity if needed (cycle types for variety)
    const type=typeMap[i % 4] || (tag==='success'?'decision':tag==='running'?'action':tag==='failed'?'obs':'thought');
    const label={'thought':'THOUGHT','action':'ACTION','obs':'OBSERVATION','decision':'DECISION'}[type];
    addReasoning(type,label,step.details,step.timestamp||nowTs());
  });
}

async function refreshOps(){
  try{
    const [health,ops,jobsResp]=await Promise.all([
      apiGet('/health'),
      apiGet('/api/v1/metrics/ops'),
      apiGet('/api/v1/pipeline/jobs?limit=10'),
    ]);
    const [timeline,spans]=await Promise.all([
      jobsResp.jobs?.[0]?.job_id ? apiGet(`/api/v1/remediation/${jobsResp.jobs[0].job_id}/timeline`) : Promise.resolve({timeline:[]}),
      jobsResp.jobs?.[0]?.job_id ? apiGet(`/api/v1/pipeline/${jobsResp.jobs[0].job_id}/spans`) : Promise.resolve({spans:[]}),
    ]);
    applyOpsSnapshot({health,ops,jobsResp,timeline,spans});

  }catch(err){
    document.getElementById('state-indicator').textContent='● DEGRADED';
    console.error(err);
  }
}

function startOpsRealtime(){
  const baseUrl = getApiBaseUrl();
  const proto = baseUrl.startsWith('https') ? 'wss' : 'ws';
  const host = new URL(baseUrl).host;
  const wsUrl = `${proto}://${host}/api/v1/ops/ws`;
  const currentKey = getApiKey();
  const subprotocols = currentKey ? [`api-key.${currentKey}`] : [];
  let ws;
  try{
    ws = new WebSocket(wsUrl, subprotocols);
  }catch(err){
    console.error('ops ws init failed', err);
    setTimeout(refreshOps, 1500);
    setTimeout(startOpsRealtime, 3000);
    return;
  }

  ws.onmessage=(event)=>{
    try{
      const payload=JSON.parse(event.data);
      if(payload?.error){
        console.warn('ops ws payload error',payload.error);
        return;
      }
      const jobs=payload.jobs||[];
      applyOpsSnapshot({
        health:payload.health||{},
        ops:payload.ops||{},
        jobsResp:{jobs},
        timeline:payload.latest_timeline||{timeline:[]},
        spans:payload.latest_spans||{spans:[]},
      });
    }catch(err){
      console.error('ops ws parse error',err);
    }
  };

  ws.onclose=async (ev)=>{
    if(ev.code===1008){
      const hasKey=await ensureApiKey('Enter X-API-Key to access real-time ops stream:');
      if(hasKey){
        startOpsRealtime();
        return;
      }
    }
    setTimeout(startOpsRealtime,2000);
  };

  ws.onerror=()=>{};
}

function startLogStream(){
  try{
    const es=new EventSource(`${getApiBaseUrl()}/api/v1/log-stream?burst=1&interval_ms=1200`);
    es.onmessage=(e)=>{
      try{
        const p=JSON.parse(e.data);
        const sev=(p.severity||'info').toLowerCase();
        const tag=severityTag(sev);
        const cls=eventClassBySeverity(sev);
        const ts=(p.timestamp||nowTs()).slice(0,8);
        const stage=(p.stage?`[${p.stage}] `:'');
        const service=(p.service?`${p.service} · `:'');
        addEventRow({ts,tag,msg:`${stage}${service}${p.message||'event'}`,cls});

        if(sev==='error')addReasoning('obs','OBSERVATION',p.message||'error signal',ts);
        else if(sev==='warning')addReasoning('action','ACTION',p.message||'warning signal',ts);
        else if(sev==='success')addReasoning('decision','DECISION',p.message||'success signal',ts);
      }catch(err){
        console.error('SSE parse error',err);
      }
    };
    es.onerror=()=>{};
  }catch(err){
    console.error('Unable to start log stream',err);
  }
}

const scenarioMap={
  api:'payment_latency_spike',
  mem:'memory_leak',
  cpu:'cpu_spike',
  db:'db_overload',
  net:'network_partition',
  cas:'cascading_failure',
};

async function triggerChaos(signal){
  const scenario=scenarioMap[signal]||'payment_latency_spike';
  if(!(await ensureApiKey('Enter X-API-Key to trigger pipeline:'))){toast('Cancelled: API key required.');return;}

  try{
    const res=await apiPost(`/api/v1/pipeline/run?scenario=${encodeURIComponent(scenario)}`);
    toast(`JOB ACCEPTED · ${res.job_id} · ${scenario}`);
    addEventRow({ts:nowTs(),tag:'TRG',msg:`pipeline requested · ${scenario} · ${res.job_id}`,cls:'trigger'});
    addReasoning('action','ACTION',`Triggered autonomous run for ${scenario} (job ${res.job_id}).`);
    refreshOps();
  }catch(err){
    toast(`INJECT FAILED · ${String(err.message||err)}`);
    addEventRow({ts:nowTs(),tag:'ERR',msg:`pipeline request failed · ${String(err.message||err)}`,cls:'anomaly'});
  }
}

document.querySelectorAll('.cb[data-signal]').forEach((button)=>{
  button.addEventListener('click',()=>{
    const signal=button.getAttribute('data-signal')||'api';
    triggerChaos(signal);
  });
});

startLogStream();
refreshOps();
startOpsRealtime();
