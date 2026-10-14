import { summarizeTasks, transitionTask, createEvent } from './core.mjs';

const stateLabel={backlog:'任务池',todo:'待办',ready:'就绪',in_progress:'进行中',review:'待审查',blocked:'已阻塞',done:'已完成'};
const stateClass={'进行中':'running','待审查':'review','已阻塞':'blocked','已完成':'done'};
const pipelineOrder=['任务池','待办','就绪','进行中','待审查','已阻塞','已完成'];
const demoTasks=[
  {id:'CODEX-DEMO',title:'Codex 原生会话：重构认证模块',status:'进行中',assignee:'Codex Observer',assigneeType:'agent',progress:0,dependencies:[],priority:'中',currentAction:'正在修改认证逻辑',artifacts:[],source:'codex',controlMode:'observed',externalId:'sess-demo',plan:['阅读代码','修改认证','运行测试'],runStatus:'running'},
  {id:'TASK-103',title:'构建知识库索引',status:'进行中',assignee:'TaskFSM Codex',assigneeType:'agent',progress:72,dependencies:[],priority:'高',currentAction:'正在运行测试',artifacts:['git://abc123'],source:'taskfsm',controlMode:'managed',runId:'run_83f21a7e',runStatus:'running',plan:['分析索引结构','实现索引','运行验证']},
  {id:'TASK-104',title:'设计检索策略',status:'待审查',assignee:'Builder',assigneeType:'agent',progress:88,dependencies:['TASK-103'],priority:'高',currentAction:'等待审查',artifacts:['retrieval-spec.md'],source:'taskfsm',controlMode:'managed'},
];
let tasks=structuredClone(demoTasks);
let events=[createEvent({actor:'Codex Observer',actorType:'agent',taskId:'CODEX-DEMO',text:'发现原生 Codex Session'}),createEvent({actor:'TaskFSM Codex',actorType:'agent',taskId:'TASK-103',text:'调用 run_tests'})];
let dashboard=null;
let selectedTaskId=tasks[0].id;
let detailTab='运行';
let liveMode=false;
let paused=false;

const $=(selector)=>document.querySelector(selector);
const escapeHtml=(value='')=>String(value).replace(/[&<>"']/g,(m)=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const selectedTask=()=>tasks.find((task)=>task.id===selectedTaskId)||tasks[0];
const avatar=(task)=>`<span class="avatar actor-${task.assigneeType}">${task.assigneeType==='agent'?'AI':escapeHtml(task.assignee?.slice(0,1)||'人')}</span>`;
const pill=(status)=>`<span class="status ${stateClass[status]||''}">${status}</span>`;
const modePill=(task)=>`<span class="chip ${task.controlMode==='observed'?'':'active'}">${task.controlMode==='observed'?'◎ 观察':'◆ 受管'}</span>`;
const bar=(value=0)=>`<span class="progress"><i style="width:${Math.max(0,Math.min(100,value))}%"></i></span>`;

function renderSummary(){
  const counts=summarizeTasks(tasks);
  const observed=tasks.filter((t)=>t.controlMode==='observed').length;
  const managed=tasks.filter((t)=>t.controlMode==='managed').length;
  const activeAgents=new Set(tasks.filter((t)=>t.status==='进行中'&&t.assigneeType==='agent').map((t)=>t.assignee)).size;
  const cards=[['🤖','活跃 Agent',activeAgents],['◎','原生会话',observed],['◆','受管任务',managed],['!','阻塞任务',counts['已阻塞']||0],['✓','已完成',counts['已完成']||0]];
  $('#summaryGrid').innerHTML=cards.map(([icon,label,value])=>`<article class="metric-card"><span class="metric-icon">${icon}</span><div><label>${label}</label><strong>${value}</strong><small>实时统计</small></div></article>`).join('')+`<article class="metric-card wide-metric"><div><label>双向 Agent 控制平面</label><small>Agent → TaskFSM 观察 / TaskFSM → Agent 调度</small></div><div class="mini-stat"><span>事件</span><strong>${events.length}</strong></div><div class="mini-stat"><span>数据源</span><strong>${liveMode?'实时':'演示'}</strong></div></article>`;
}

function renderPipeline(){const counts=summarizeTasks(tasks);$('#pipeline').innerHTML=pipelineOrder.map((status)=>`<div class="pipeline-item ${status==='进行中'?'active':''}"><span class="pipe-dot"></span><strong><span>${status}</span><b>${counts[status]||0}</b></strong><small>${status==='已阻塞'?'异常/等待分支':'统一状态投影'}</small></div>`).join('');}

function taskNode(task,index){const pos=[[32,15],[62,16],[32,43],[62,45],[32,70],[62,70]][index%6];return `<button class="topo-node task ${task.id===selectedTaskId?'selected':''}" data-task="${task.id}" style="left:${pos[0]}%;top:${pos[1]}%"><small>${task.source==='codex'?'Codex · ':''}${escapeHtml(task.id)}</small><strong>${escapeHtml(task.title)}</strong><div class="node-foot">${pill(task.status)}${modePill(task)}</div>${task.progress?bar(task.progress):''}</button>`;}
function renderTopology(){
  const visible=tasks.filter((t)=>['进行中','待审查','已阻塞','已完成'].includes(t.status)).slice(0,6);
  const agents=[...new Set(visible.map((t)=>t.assignee).filter(Boolean))].slice(0,3);
  const edges=`<svg viewBox="0 0 1000 480" preserveAspectRatio="none"><path class="edge active" d="M150 100 C250 100 260 100 335 110"/><path class="edge active" d="M150 225 C260 225 260 230 335 235"/><path class="edge warning" d="M520 120 C600 120 590 120 650 120"/></svg>`;
  $('#topology').innerHTML=edges+agents.map((name,i)=>`<div class="topo-node agent" style="left:7%;top:${18+i*27}%"><div class="agent-line"><span class="avatar actor-agent">AI</span><div><strong>${escapeHtml(name)}</strong><small>Codex / Agent</small></div></div><span class="heartbeat">● 在线</span></div>`).join('')+visible.map(taskNode).join('')+`<div class="topo-node service" style="left:86%;top:35%"><strong>TaskFSM</strong><small>FSM · Event · Runtime</small></div>`;
  document.querySelectorAll('[data-task]').forEach((el)=>el.addEventListener('click',()=>selectTask(el.dataset.task)));
}

function renderRunningTasks(){
  const running=tasks.filter((t)=>['进行中','已阻塞','待审查'].includes(t.status)).slice(0,8);
  $('#runningCount').textContent=`(${running.length})`;
  $('#runningTasks').innerHTML=`<div class="task-row head"><span>任务</span><span>执行者</span><span>模式</span><span>状态</span></div>`+running.map((t)=>`<button class="task-row ${t.id===selectedTaskId?'selected':''}" data-row-task="${t.id}"><span><b>${escapeHtml(t.id)}</b><small>${escapeHtml(t.title)}</small></span><span class="assignee">${avatar(t)}${escapeHtml(t.assignee)}</span><span>${modePill(t)}</span><span>${pill(t.status)}</span></button>`).join('');
  document.querySelectorAll('[data-row-task]').forEach((el)=>el.addEventListener('click',()=>selectTask(el.dataset.rowTask)));
}

function renderEvents(){$('#eventFeed').innerHTML=events.slice(0,12).map((event)=>`<div class="event severity-${event.severity||'info'}"><time>${event.time||'--:--:--'}</time><span>${event.severity==='error'?'!':'◆'}</span><div><b>${escapeHtml(event.actor||'系统')}</b> ${escapeHtml(event.text)}</div></div>`).join('')||'<div class="empty">暂无事件</div>';}

function dependenciesView(task){
  const upstream=(task.dependencies||[]).map((id)=>tasks.find((t)=>t.id===id)).filter(Boolean);
  const downstream=tasks.filter((t)=>(t.dependencies||[]).includes(task.id));
  const cards=(items,empty)=>items.length?items.map((t)=>`<button class="dependency-card" data-dependency="${t.id}"><strong>${escapeHtml(t.id)} · ${escapeHtml(t.title)}</strong>${pill(t.status)}</button>`).join(''):`<div class="empty">${empty}</div>`;
  return `<section class="detail-section"><h3>依赖于（${upstream.length}）</h3>${cards(upstream,'没有上游依赖')}</section><section class="detail-section"><h3>被依赖（${downstream.length}）</h3>${cards(downstream,'没有下游任务')}</section>`;
}

function runtimeView(task){
  const lease=task.leaseSeconds||0;
  const plan=(task.plan||[]).length?`<ol>${task.plan.map((item)=>`<li>${escapeHtml(item)}</li>`).join('')}</ol>`:'<div class="empty">Agent 尚未暴露 Plan</div>';
  return `<section class="detail-section"><h3>运行身份</h3><dl class="kv"><dt>来源</dt><dd>${task.source==='codex'?'Codex 原生 Session':'TaskFSM'}</dd><dt>控制模式</dt><dd>${task.controlMode==='observed'?'Observed · 只读观察':'Managed · TaskFSM 调度'}</dd><dt>Session</dt><dd>${escapeHtml(task.externalId||'—')}</dd><dt>Run</dt><dd>${escapeHtml(task.runId||'—')}</dd><dt>Workspace</dt><dd>${escapeHtml(task.workspace||'—')}</dd><dt>运行状态</dt><dd>${escapeHtml(task.runStatus||'—')}</dd><dt>租约剩余</dt><dd>${lease?`${Math.floor(lease/60)}m ${lease%60}s`:'—'}</dd><dt>当前动作</dt><dd>${escapeHtml(task.currentAction||'—')}</dd></dl></section><section class="detail-section"><h3>Agent 原生执行计划</h3>${plan}</section>`;
}
function overviewView(task){const policy=task.controlMode==='observed'?'此任务来自 Agent 内部，TaskFSM 仅做状态投影和可视化，不拥有调度权。':'此任务由 TaskFSM 管理，Agent 只能通过受控动作请求状态迁移。';return `<section class="detail-section"><h3>任务概览</h3><p>${escapeHtml(policy)}</p><dl class="kv"><dt>优先级</dt><dd>${task.priority}</dd><dt>当前状态</dt><dd>${task.status}</dd><dt>模式</dt><dd>${task.controlMode}</dd></dl></section>`;}
function eventView(task){const rows=events.filter((e)=>e.taskId===task.id);return `<section class="detail-section"><h3>状态与运行事件</h3>${rows.map((e)=>`<div class="timeline-event"><b>${e.time||''} · ${escapeHtml(e.actor)}</b><span>${escapeHtml(e.text)}</span></div>`).join('')||'<div class="empty">暂无事件</div>'}</section>`;}
function artifactView(task){return `<section class="detail-section"><h3>产物</h3>${(task.artifacts||[]).map((a)=>`<div class="artifact"><b>▣ ${escapeHtml(a)}</b><small>可作为后续任务输入</small></div>`).join('')||'<div class="empty">尚未提交产物</div>'}</section>`;}

function renderDetail(){
  const task=selectedTask();if(!task){$('#taskDetail').innerHTML='<div class="empty">暂无任务</div>';return;}
  const tabs=['概览','运行','依赖','事件','产物'];
  const content={概览:overviewView(task),运行:runtimeView(task),依赖:dependenciesView(task),事件:eventView(task),产物:artifactView(task)}[detailTab];
  const observedNotice=task.controlMode==='observed'?'<div class="detail-actions"><span class="chip">Observed：TaskFSM 不改变此任务状态</span></div>':`<div class="detail-actions"><button id="pauseBtn" class="action">${paused?'▶ 恢复':'Ⅱ 暂停'}</button><button id="reviewBtn" class="action primary">提交审查</button><button id="completeBtn" class="action success">批准并完成</button></div>`;
  $('#taskDetail').innerHTML=`<div class="detail-head"><small>${escapeHtml(task.id)}</small><h1>${escapeHtml(task.title)}</h1><div>${pill(task.status)} ${modePill(task)}</div></div><div class="tabs">${tabs.map((tab)=>`<button class="tab ${tab===detailTab?'active':''}" data-tab="${tab}">${tab}</button>`).join('')}</div><div class="detail-content">${content}</div>${observedNotice}`;
  document.querySelectorAll('[data-tab]').forEach((el)=>el.addEventListener('click',()=>{detailTab=el.dataset.tab;renderDetail();}));
  document.querySelectorAll('[data-dependency]').forEach((el)=>el.addEventListener('click',()=>selectTask(el.dataset.dependency)));
  if(task.controlMode!=='observed'){$('#pauseBtn')?.addEventListener('click',togglePause);$('#reviewBtn')?.addEventListener('click',submitReview);$('#completeBtn')?.addEventListener('click',markComplete);}
}

function renderAll(){renderSummary();renderPipeline();renderTopology();renderRunningTasks();renderEvents();renderDetail();}
function selectTask(id){if(!tasks.some((t)=>t.id===id))return;selectedTaskId=id;detailTab='运行';renderAll();}
function showToast(message,type=''){const el=$('#toast');el.textContent=message;el.className=`toast show ${type}`;clearTimeout(showToast.timer);showToast.timer=setTimeout(()=>el.className='toast',2800);}
function pushEvent(text,severity='info',actor='系统',taskId=selectedTaskId){events.unshift(createEvent({actor,taskId,text,severity}));renderEvents();}
function applyTransition(nextStatus,action){const current=selectedTask();if(current.controlMode==='observed'){showToast('Observed 任务由外部 Agent 状态驱动','error');return false;}const result=transitionTask(current,nextStatus,tasks);if(!result.allowed){showToast(`状态机守卫拒绝：${result.reason}`,'error');return false;}tasks=tasks.map((t)=>t.id===current.id?{...result.task,currentAction:action,progress:nextStatus==='已完成'?100:t.progress}:t);pushEvent(`${current.id} ${current.status} → ${nextStatus}`,'success',current.assignee,current.id);renderAll();return true;}
function togglePause(){paused=!paused;showToast(paused?'已暂停当前运行':'已恢复当前运行');renderDetail();}
async function submitReview(){const task=selectedTask();if(task.controlMode==='observed'){showToast('Observed 任务不能由 TaskFSM 提交审查','error');return;}if(task.status!=='进行中'){showToast('只有进行中任务可提交审查','error');return;}if(liveMode){showToast('实时模式下必须由持有租约的 Agent 通过 MCP/SDK 提交审查');return;}applyTransition('待审查','等待审查');}
async function markComplete(){
  const task=selectedTask();if(task.controlMode==='observed'){showToast('Observed 任务不能由 TaskFSM 完成','error');return;}
  if(!liveMode){applyTransition('已完成','已完成');return;}
  if(task.status!=='待审查'){showToast('只有待审查任务可批准完成','error');return;}
  try{
    let response=await fetch(`/api/tasks/${task.id}/reviews`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reviewer:'human:alice',decision:'approved',reason:'通过运行控制台批准'})});
    if(!response.ok)throw new Error((await response.json()).detail||'审查批准失败');
    response=await fetch(`/api/tasks/${task.id}/complete`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({actor:'human:alice'})});
    if(!response.ok)throw new Error((await response.json()).detail||'任务完成失败');
    await refreshFromApi();showToast('审查已批准，任务已完成','success');
  }catch(error){showToast(error.message,'error');}
}

function mapDashboard(data){
  dashboard=data;
  const agents=new Map((data.agents||[]).map((a)=>[a.id,a]));
  const leases=new Map((data.active_leases||[]).map((l)=>[l.task_id,l]));
  const runs=new Map();for(const run of data.runs||[]){if(!runs.has(run.task_id))runs.set(run.task_id,run);}
  const artifactMap=new Map();(data.artifacts||[]).forEach((a)=>{const list=artifactMap.get(a.task_id)||[];list.push(a.uri);artifactMap.set(a.task_id,list);});
  tasks=(data.tasks||[]).map((t)=>{const agent=agents.get(t.assignee_id);const lease=leases.get(t.id);const run=runs.get(t.id);return {id:t.id,title:t.title,status:stateLabel[t.status]||t.status,assignee:agent?.name||(t.assignee_type==='human'?'Alice':'未分配'),assigneeId:t.assignee_id,assigneeType:t.assignee_type||'human',progress:t.progress||0,dependencies:t.dependency_ids||[],priority:t.priority==='high'?'高':t.priority==='low'?'低':'中',currentAction:t.current_action||run?.current_event?.message||'',leaseSeconds:lease?.expires_at?Math.max(0,Math.floor((new Date(lease.expires_at)-Date.now())/1000)):0,heartbeatSeconds:agent?Math.max(0,Math.floor((Date.now()-new Date(agent.last_heartbeat_at))/1000)):0,runId:run?.id||'—',runStatus:run?.status||'—',workspace:run?.workspace||t.source_metadata?.cwd||'',externalId:t.external_id||run?.external_session_id||'',source:t.source||'taskfsm',controlMode:t.control_mode||'managed',plan:run?.plan_snapshot||[],artifacts:artifactMap.get(t.id)||[]};});
  events=(data.events||[]).slice().reverse().map((e)=>({id:`evt-${e.id}`,time:new Date(e.created_at).toLocaleTimeString('zh-CN',{hour12:false}),actor:e.actor_id,actorType:e.actor_type,taskId:e.payload?.task_id||e.entity_id,severity:e.event_type.includes('expired')||e.event_type.includes('failed')?'error':e.event_type.includes('completed')?'success':'info',text:`${e.event_type}${e.payload?.message?` · ${e.payload.message}`:''}`}));
  if(!tasks.some((t)=>t.id===selectedTaskId))selectedTaskId=tasks[0]?.id||selectedTaskId;
}
async function refreshFromApi(){const response=await fetch('/api/dashboard',{cache:'no-store'});if(!response.ok)throw new Error('API 不可用');mapDashboard(await response.json());liveMode=true;$('#connectionState').textContent='● 实时连接';$('#connectionState').classList.add('active');renderAll();}
function connectEvents(){const source=new EventSource('/api/events/stream');source.onmessage=()=>refreshFromApi().catch(()=>{});source.onerror=()=>{$('#connectionState').textContent='● 正在重连';};}
async function syncCodex(){
  const button=$('#codexSync');button.disabled=true;button.textContent='同步中…';
  try{const response=await fetch('/api/integrations/codex/sync',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({limit:200})});if(!response.ok)throw new Error((await response.json()).detail||'同步失败');const result=await response.json();await refreshFromApi();showToast(`Codex 同步完成：发现 ${result.discovered}，同步 ${result.synced}`,'success');}
  catch(error){showToast(error.message,'error');}
  finally{button.disabled=false;button.textContent='↻ 同步 Codex';}
}
function wireGlobal(){
  document.querySelectorAll('.main-nav button').forEach((button)=>button.addEventListener('click',()=>{if(button.dataset.view!=='runtime')showToast('当前版本聚焦运行视图，其余模块保留导航入口');}));
  $('#globalSearch').addEventListener('input',(event)=>{const q=event.target.value.trim().toLowerCase();if(!q)return;const hit=tasks.find((t)=>`${t.id}${t.title}${t.assignee}${t.externalId||''}`.toLowerCase().includes(q));if(hit)selectTask(hit.id);});
  $('#codexSync')?.addEventListener('click',syncCodex);
}
async function boot(){wireGlobal();renderAll();try{await refreshFromApi();connectEvents();}catch{$('#connectionState').textContent='离线演示模式';showToast('后端未连接，显示本地演示数据','error');}}
boot();
setInterval(()=>{if(liveMode)refreshFromApi().catch(()=>{});},15000);
