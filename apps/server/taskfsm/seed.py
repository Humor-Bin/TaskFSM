from taskfsm.domain.service import TaskFSMService


def seed_demo(service: TaskFSMService):
    if service.list_tasks():
        return
    nova = service.register_agent('Nova', 'codex', ['python', 'rag', 'testing'])
    builder = service.register_agent('Builder', 'generic', ['python', 'api', 'architecture'])
    coder = service.register_agent('Coder', 'generic', ['python', 'testing'])
    ops = service.register_agent('Ops', 'generic', ['ops', 'deploy'])

    service.create_task('准备检索数据集', status='done', task_id='TASK-089')
    service.create_task('清洗历史数据', status='backlog', task_id='TASK-090')
    service.create_task('定义评价指标', status='backlog', task_id='TASK-091')
    service.create_task('准备部署环境', status='todo', task_id='TASK-092')
    service.create_task('选择向量数据库', status='ready', required_capabilities=['rag'], task_id='TASK-093')
    service.create_task('设计系统架构', status='in_progress', task_id='TASK-101')
    t103 = service.create_task('构建知识库索引', status='ready', priority='high', required_capabilities=['python','rag'], dependency_ids=['TASK-089'], task_id='TASK-103')
    service.create_task('设计检索策略', status='review', priority='high', dependency_ids=['TASK-103'], task_id='TASK-104')
    t105 = service.create_task('实现 API 接口', status='ready', required_capabilities=['python','api'], dependency_ids=['TASK-089'], task_id='TASK-105')
    service.create_task('编写测试用例', status='todo', required_capabilities=['testing'], dependency_ids=['TASK-105'], task_id='TASK-106')
    service.create_task('修复登录问题', status='blocked', priority='high', task_id='TASK-107')
    service.create_task('优化数据处理', status='done', task_id='TASK-108')
    service.create_task('接入审计日志', status='done', task_id='TASK-109')

    service.claim_task(t103.id, nova.id)
    service.report_progress(t103.id, nova.id, 72, '正在调用 search_code')
    service.submit_artifact(t103.id, nova.id, 'report', 'memory://index-plan.md')

    service.claim_task(t105.id, builder.id)
    service.report_progress(t105.id, builder.id, 45, '正在生成接口层')
