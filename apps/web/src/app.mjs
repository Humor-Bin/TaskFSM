import { summarizeTasks, transitionTask, createEvent } from './core.mjs';

const stateLabel = {backlog:'任务池',todo:'待办',ready:'就绪',in_progress:'进行中',review:'待审查',blocked:'已阻塞',done:'已完成'};
const stateClass = {'进行中':'running','待审查':'review','已阻塞':'blocked','已完成':'done'};
const pipelineOrder = ['任务池','待办','就绪','进行中','待审查','已阻塞','已完成'];
const demoTasks = [
  {id:'TASK-089',title:'准备检索数据集',status:'已完成',assignee:'Data',assigneeType:'agent',progress:100,dependencies:[],priority:'中',currentAction:'数据集已准备',artifacts:['dataset-v3.json']},
  {id:'TASK-103',title:'构建知识库索引',status:'进行中',assignee:'Nova',assigneeType:'agent',progress:72,dependencies:['TASK-089'],priority:'高',currentAction:'正在调用 search_code',leaseSeconds:378,heartbeatSeconds:2,runId:'run_83f21a7e',artifacts:['index-plan.md']},
  {id:'TASK-104',title:'设计检索策略',status:'待审查',assignee:'Builder',assigneeType:'agent',progress:88,dependencies:['TASK-103'],priority:'高',currentAction:'等待审查',artifacts:['retrieval-spec.md']},
  {id:'TASK-105',title:'实现 API 接口',status:'进行中',assignee:'Builder',assigneeType:'agent',progress:45,dependencies:['TASK-089'],priority:'中',currentAction:'正在生成接口层',leaseSeconds:512,artifacts:[]},
  {id:'TASK-106',title:'编写测试用例',status:'待办',assignee:'Coder',assigneeType:'agent',progress:0,dependencies:['TASK-105'],priority:'中',currentAction:'等待依赖',artifacts:[]},
  {id:'TASK-107',title:'修复登录问题',status:'已阻塞',assignee:'Nova',assigneeType:'agent',progress:38,dependencies:[],priority:'高',currentAction:'测试失败：等待凭据',artifacts:['error.log']},
  {id:'TASK-108',title:'优化数据处理',status:'已完成',assignee:'Coder',assigneeType:'agent',progress:100,dependencies:[],priority:'中',currentAction:'已完成',artifacts:['processor.patch']},
  {id:'TASK-101',title:'设计系统架构',status:'进行中',assignee:'Alice',assigneeType:'human',progress:64,dependencies:[],priority:'高',currentAction:'人工设计中',artifacts:['architecture.md']},
];
let tasks = structuredClone(demoTasks);
let events = [createEvent({actor:'系统',taskId:'TASK-103',text:'为 TASK-103 创建执行租约（10m）'}),createEvent({actor:'Nova',actorType:'agent',taskId:'TASK-103',text:'调用工具 search_code'}),createEvent({actor:'系统',taskId:'TASK-107',text:'测试失败，被标记为阻塞',severity:'error'})];
let dashboard = null;
let selectedTaskId = 'TASK-103';
let detailTab = '运行';
let liveMode = false;
let paused = false;

const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value='') => String(value).replace(/[&<>"']/g,(m)=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const selectedTask = () => tasks.find((task)=>task.id===selectedTaskId) || tasks[0];
const avatar = (task) => `<span class="avatar actor-${task.assigneeType}">${task.assigneeType==='agent'?'AI':escapeHtml(task.assignee?.slice(0,1)||'人')}</span>`;
const pill = (status) => `<span class="status ${stateClass[status]||''}">${status}</span>`;
const bar = (value=0) => `<span class="progress"><i style="width:${Math.max(0,Math.min(100,value))}%"></i></span>`;

function renderSummary(){
  const counts=summarizeTasks(tasks);
  const activeAgents=new Set(tasks.filter((t)=>t.status==='进行中'&&t.assigneeType==='agent').map((t)=>t.assignee)).size;
  const cards=[['🤖','运行中 Agent',activeAgents],['▤','执行中任务',counts['进行中']||0],['◉','等待审查',counts['待审查']||0],['!','阻塞任务',counts['已阻塞']||0],['✓','已完成',counts['已完成']||0]];
  $('#summaryGrid').innerHTML=cards.map(([icon,label,value])=>`<article class="metric-card"><span class="metric-icon">${icon}</span><div><label>${label}</label><strong>${value}</strong><small>实时统计</small></div></article>`).join('')+`<article class="metric-card wide-metric"><div><label>任务吞吐 · 最近 1 小时</label><div class="spark">${[12,22,16,28,19,31,24,15,27,21,34,18].map((h)=>`<i style="height:${h}px"></i>`).join('')}</div></div><div class="mini-stat"><span>状态迁移</span><strong>${events.length}</strong></div><div class="mini-stat"><span>数据源</span><strong>${liveMode?'实时':'演示'}</strong></div></article>`;
}

function renderPipeline(){
  const counts=summarizeTasks(tasks);
  $('#pipeline').innerHTML=pipelineOrder.map((status)=>`<div class="pipeline-item ${status==='进行中'?'active':''}"><span class="pipe-dot"></span><strong><span>${status}</span><b>${counts[status]||0}</b></strong><small>${status==='已阻塞'?'异常分支':'平均停留 · 实时'}</small></div>`).join('');
}

function taskNode(task,index){
  const pos=[[33,16],[62,18],[34,43],[62,45],[33,70],[62,70]][index%6];
  return `<button class="topo-node task ${task.id===selectedTaskId?'selected':''}" data-task="${task.id}" style="left:${pos[0]}%;top:${pos[1]}%"><small>${task.id}</small><strong>${escapeHtml(task.title)}</strong><div class="node-foot">${pill(task.status)}<span>${task.progress||0}%</span></div>${bar(task.progress||0)}</button>`;
}
function renderTopology(){
  const visible=tasks.filter((t)=>['进行中','待审查','已阻塞','已完成'].includes(t.status)).slice(0,6);
  const agents=[['Nova','AI Agent',8,18],['Builder','AI Agent',8,45],['Alice','人类监督',8,72]];
  const edges=`<svg viewBox="0 0 1000 480" preserveAspectRatio="none"><path class="edge active" d="M150 100 C260 100 250 100 340 110"/><path class="edge active" d="M150 225 C270 225 250 225 340 240"/><path class="edge warning" d="M520 120 C600 120 590 120 650 120"/><path class="edge danger" d="M520 350 C610 350 590 350 650 350"/></svg>`;
  $('#topology').innerHTML=edges+agents.map(([name,role,left,top])=>`<div class="topo-node agent" style="left:${left}%;top:${top}%"><div class="agent-line"><span class="avatar actor-${role==='人类监督'?'human':'agent'}">${role==='人类监督'?'A':'AI'}</span><div><strong>${name}</strong><small>${role}</small></div></div><span class="heartbeat">● 在线</span></div>`).join('')+visible.map(taskNode).join('')+`<div class="topo-node service" style="left:86%;top:35%"><strong>知识库服务</strong><small>● 正常</small></div>`;
  document.querySelectorAll('[data-task]').forEach((el)=>el.addEventListener('click',()=>selectTask(el.dataset.task)));
}

function renderRunningTasks(){
  const running=tasks.filter((t)=>['进行中','已阻塞','待审查'].includes(t.status)).slice(0,6);
  $('#runningCount').textContent=`(${running.length})`;
  $('#runningTasks').innerHTML=`<div class="task-row head"><span>任务</span><span>执行者</span><span>状态</span><span>进度</span></div>`+running.map((t)=>`<button class="task-row ${t.id===selectedTaskId?'selected':''}" data-row-task="${t.id}"><span><b>${t.id}</b><small>${escapeHtml(t.title)}</small></span><span class="assignee">${avatar(t)}${escapeHtml(t.assignee)}</span><span>${pill(t.status)}</span><span>${bar(t.progress)} ${t.progress||0}%</span></button>`).join('');
  document.querySelectorAll('[data-row-task]').forEach((el)=>el.addEventListener('click',()=>selectTask(el.dataset.rowTask)));
}

function renderEvents(){
  $('#eventFeed').innerHTML=events.slice(0,10).map((event)=>`<div class="event severity-${event.severity||'info'}"><time>${event.time||'--:--:--'}</time><span>${event.severity==='error'?'!':'◆'}</span><div><b>${escapeHtml(event.actor||'系统')}</b> ${escapeHtml(event.text)}</div></div>`).join('')||'<div class="empty">暂无事件</div>';
}

function dependenciesView(task){
  const upstream=(task.dependencies||[]).map((id)=>tasks.find((t)=>t.id===id)).filter(Boolean);
  const downstream=tasks.filter((t)=>(t.dependencies||[]).includes(task.id));
  const cards=(items,empty)=>items.length?items.map((t)=>`<button class="dependency-card" data-dependency="${t.id}"><strong>${t.id} · ${escapeHtml(t.title)}</strong>${pill(t.status)}</button>`).join(''):`<div class="empty">${empty}</div>`;
  return `<section class="detail-section"><h3>依赖于（${upstream.length}）</h3>${cards(upstream,'没有上游依赖')}</section><section class="detail-section"><h3>被依赖（${downstream.length}）</h3>${cards(downstream,'没有下游任务')}</section>`;
}
function runtimeView(task){
  const lease=task.leaseSeconds||0;
  return `<section class="detail-section"><h3>运行状态</h3><dl class="kv"><dt>执行者</dt><dd>${avatar(task)} ${escapeHtml(task.assignee)}</dd><dt>运行 ID</dt><dd>${escapeHtml(task.runId||'—')}</dd><dt>租约剩余</dt><dd>${lease?`${Math.floor(lease/60)}m ${lease%60}s`:'—'}</dd><dt>心跳</dt><dd class="ok">● ${task.heartbeatSeconds??0} 秒前</dd><dt>当前动作</dt><dd>${escapeHtml(task.currentAction||'—')}</dd></dl>${bar(task.progress||0)}</section><section class="detail-section"><h3>最近工具调用</h3><div class="tool-log"><div>search_code <span>src/retriever.ts</span></div><div>read_file <span>docs/architecture.md</span></div><div>run_tests <span>pytest / npm test</span></div></div></section>`;
}
function overviewView(task){return `<section class="detail-section"><h3>任务概览</h3><p>${escapeHtml(task.title)} 是 TaskFSM 中的可审计执行单元。状态由服务端 FSM 控制，Agent 只能请求动作而不能直接写状态。</p><dl class="kv"><dt>优先级</dt><dd>${task.priority}</dd><dt>当前状态</dt><dd>${task.status}</dd><dt>进度</dt><dd>${task.progress||0}%</dd></dl></section>`;}
function eventView(task){const rows=events.filter((e)=>e.taskId===task.id);return `<section class="detail-section"><h3>状态与运行事件</h3>${rows.map((e)=>`<div class="timeline-event"><b>${e.time||''} · ${escapeHtml(e.actor)}</b><span>${escapeHtml(e.text)}</span></div>`).join('')||'<div class="empty">暂无事件</div>'}</section>`;}
function artifactView(task){return `<section class="detail-section"><h3>产物</h3>${(task.artifacts||[]).map((a)=>`<div class="artifact"><b>▣ ${escapeHtml(a)}</b><small>可作为后续任务输入</small></div>`).join('')||'<div class="empty">尚未提交产物</div>'}</section>`;}

function renderDetail(){
  const task=selectedTask(); if(!task){$('#taskDetail').innerHTML='<div class="empty">暂无任务</div>';return;}
  const tabs=['概览','运行','依赖','事件','产物'];
  const content={概览:overviewView(task),运行:runtimeView(task),依赖:dependenciesView(task),事件:eventView(task),产物:artifactView(task)}[detailTab];
  $('#taskDetail').innerHTML=`<div class="detail-head"><small>${task.id}</small><h1>${escapeHtml(task.title)}</h1>${pill(task.status)}</div><div class="tabs">${tabs.map((tab)=>`<button class="tab ${tab===detailTab?'active':''}" data-tab="${tab}">${tab}</button>`).join('')}</div><div class="detail-content">${content}</div><div class="detail-actions"><button id="pauseBtn" class="action">${paused?'▶ 恢复':'Ⅱ 暂停'}</button><button id="reviewBtn" class="action primary">提交审查</button><button id="completeBtn" class="action success">批准并完成</button></div>`;
  document.querySelectorAll('[data-tab]').forEach((el)=>el.addEventListener('click',()=>{detailTab=el.dataset.tab;renderDetail();}));
  document.querySelectorAll('[data-dependency]').forEach((el)=>el.addEventListener('click',()=>selectTask(el.dataset.dependency)));
  $('#pauseBtn').addEventListener('click',togglePause); $('#reviewBtn').addEventListener('click',submitReview); $('#completeBtn').addEventListener('click',markComplete);
}

function renderAll(){renderSummary();renderPipeline();renderTopology();renderRunningTasks();renderEvents();renderDetail();}
function selectTask(id){if(!tasks.some((t)=>t.id===id))return;selectedTaskId=id;detailTab='运行';renderAll();}
function showToast(message,type=''){const el=$('#toast');el.textContent=message;el.className=`toast show ${type}`;clearTimeout(showToast.timer);showToast.timer=setTimeout(()=>el.className='toast',2800);}
function pushEvent(text,severity='info',actor='系统',taskId=selectedTaskId){events.unshift(createEvent({actor,taskId,text,severity}));renderEvents();}
function applyTransition(nextStatus,action){const current=selectedTask();const result=transitionTask(current,nextStatus,tasks);if(!result.allowed){showToast(`状态机守卫拒绝：${result.reason}`,'error');return false;}tasks=tasks.map((t)=>t.id===current.id?{...result.task,currentAction:action,progress:nextStatus==='已完成'?100:t.progress}:t);pushEvent(`${current.id} ${current.status} → ${nextStatus}`,'success',current.assignee,current.id);renderAll();return true;}
function togglePause(){paused=!paused;showToast(paused?'已暂停当前运行':'已恢复当前运行');renderDetail();}
async function submitReview(){const task=selectedTask();if(task.status!=='进行中'){showToast('只有进行中任务可提交审查','error');return;}if(liveMode){showToast('实时模式下必须由持有租约的 Agent 通过 SDK 提交审查');return;}applyTransition('待审查','等待审查');}
async function markComplete(){
  const task=selectedTask();
  if(!liveMode){applyTransition('已完成','已完成');return;}
  if(task.status!=='待审查'){showToast('只有待审查任务可批准完成','error');return;}
  try{
    let response=await fetch(`/api/tasks/${task.id}/reviews`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reviewer:'human:alice',decision:'approved',reason:'通过运行控制台批准'})});
    if(!response.ok)throw new Error((await response.json()).detail||'审查批准失败');
    response=await fetch(`/api/tasks/${task.id}/complete`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({actor:'human:alice'})});
    if(!response.ok)throw new Error((await response.json()).detail||'任务完成失败');
    await refreshFromApi(); showToast('审查已批准，任务已完成','success');
  }catch(error){showToast(error.message,'error');}
}

function mapDashboard(data){
  dashboard=data;
  const agents=new Map((data.agents||[]).map((a)=>[a.id,a]));
  const leases=new Map((data.active_leases||[]).map((l)=>[l.task_id,l]));
  const runs=new Map((data.runs||[]).map((r)=>[r.task_id,r]));
  const artifactMap=new Map();(data.artifacts||[]).forEach((a)=>{const list=artifactMap.get(a.task_id)||[];list.push(a.uri);artifactMap.set(a.task_id,list);});
  tasks=(data.tasks||[]).map((t)=>{const agent=agents.get(t.assignee_id);const lease=leases.get(t.id);const run=runs.get(t.id);return {id:t.id,title:t.title,status:stateLabel[t.status]||t.status,assignee:agent?.name||(t.assignee_type==='human'?'Alice':'未分配'),assigneeId:t.assignee_id,assigneeType:t.assignee_type||'human',progress:t.progress||0,dependencies:t.dependency_ids||[],priority:t.priority==='high'?'高':t.priority==='low'?'低':'中',currentAction:t.current_action||'',leaseSeconds:lease?.expires_at?Math.max(0,Math.floor((new Date(lease.expires_at)-Date.now())/1000)):0,heartbeatSeconds:agent?Math.max(0,Math.floor((Date.now()-new Date(agent.last_heartbeat_at))/1000)):0,runId:run?.id||'—',artifacts:artifactMap.get(t.id)||[]};});
  events=(data.events||[]).slice().reverse().map((e)=>({id:`evt-${e.id}`,time:new Date(e.created_at).toLocaleTimeString('zh-CN',{hour12:false}),actor:e.actor_id,actorType:e.actor_type,taskId:e.entity_id,severity:e.event_type.includes('expired')?'error':e.event_type.includes('completed')?'success':'info',text:`${e.event_type} · ${e.entity_id}`}));
  if(!tasks.some((t)=>t.id===selectedTaskId))selectedTaskId=tasks[0]?.id||selectedTaskId;
}
async function refreshFromApi(){const response=await fetch('/api/dashboard',{cache:'no-store'});if(!response.ok)throw new Error('API 不可用');mapDashboard(await response.json());liveMode=true;$('#connectionState').textContent='● 实时连接';$('#connectionState').classList.add('active');renderAll();}
function connectEvents(){const source=new EventSource('/api/events/stream');source.onmessage=()=>refreshFromApi().catch(()=>{});source.onerror=()=>{$('#connectionState').textContent='● 正在重连';};}
function wireGlobal(){
  document.querySelectorAll('.main-nav button').forEach((button)=>button.addEventListener('click',()=>{if(button.dataset.view!=='runtime')showToast('当前版本优先实现运行视图，其余模块保留导航入口');}));
  $('#globalSearch').addEventListener('input',(event)=>{const q=event.target.value.trim().toLowerCase();if(!q)return;const hit=tasks.find((t)=>`${t.id}${t.title}${t.assignee}`.toLowerCase().includes(q));if(hit)selectTask(hit.id);});
}
async function boot(){wireGlobal();renderAll();try{await refreshFromApi();connectEvents();}catch{$('#connectionState').textContent='离线演示模式';showToast('后端未连接，显示本地演示数据','error');}}
boot();
setInterval(()=>{if(liveMode)refreshFromApi().catch(()=>{});},15000);
