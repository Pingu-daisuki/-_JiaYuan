import { PresentationFile, FileBlob } from "@oai/artifact-tool";

// Template-following provenance: template-starter.pptx is imported with PresentationFile.importPptx below.

const input = process.argv[2];
const output = process.argv[3];
if (!input || !output) throw new Error("Usage: node edit-campus-supplement.mjs <starter.pptx> <output.pptx>");

const presentation = await PresentationFile.importPptx(await FileBlob.load(input));

function slideAt(number) {
  const slide = presentation.slides.items[number - 1];
  if (!slide) throw new Error(`Missing output slide ${number}`);
  return slide;
}

function rewrite(slideNumber, values) {
  const slide = slideAt(slideNumber);
  for (const [name, next] of Object.entries(values)) {
    const shape = slide.shapes.items.find((item) => item.name === name);
    if (!shape) throw new Error(`Missing inherited shape ${name} on output slide ${slideNumber}`);
    const previous = String(shape.text);
    if (!previous) throw new Error(`Inherited shape ${name} on output slide ${slideNumber} has no text`);
    const previousLines = previous.split("\n");
    const nextLines = next.split("\n");
    if (previousLines.length > 1 && previousLines.length === nextLines.length) {
      shape.text = next;
    } else {
      shape.text.replace(previous, next);
    }
  }
}

rewrite(10, {
  "kicker-6": "09 · 校园服务访问",
  "title-6": "一份本地账号配置，分成两条站点会话",
  "footer-6": "10",
  "retrieval-title-0": "账号统一登记",
  "retrieval-body-0": "学号与密码先经畅课认证校验，再写入本机 campus_config，三个模块共用身份选择。",
  "retrieval-title-1": "畅课会话",
  "retrieval-body-1": "xmulogin(type=3) 返回已登录 Session；复用 Cookie 访问 profile、rollcalls 与 todos。",
  "retrieval-title-2": "XMUOJ 会话",
  "retrieval-body-2": "独立 Session：GET 首页取得 CSRF，再 POST /api/login；随后调用竞赛、题目与提交接口。",
  "retrieval-title-3": "异步与流式",
  "retrieval-body-3": "同步请求交给 asyncio.to_thread；签到与 OJ 通过 SSE 持续回传长任务日志。",
  "retrieval-outcome-text": "本地账号入口统一；畅课与 XMUOJ 仍分别维护 Cookie、CSRF 与接口协议。",
});

rewrite(11, {
  "kicker-5": "10 · 签到实现",
  "title-5": "签到引擎持续完成发现漏签、策略判断与自动提交",
  "footer-5": "11",
  "ingest-title-0": "读取策略",
  "ingest-body-0": "账号 / 轮询间隔\n时间段 / 人数阈值",
  "ingest-title-1": "认证会话",
  "ingest-body-1": "xmulogin 登录\n复用畅课 Session",
  "ingest-title-2": "循环巡航",
  "ingest-body-2": "按间隔轮询\nrollcalls 接口",
  "ingest-title-3": "策略过滤",
  "ingest-body-3": "仅处理 absent\n未达阈值继续等待",
  "ingest-title-4": "执行签到",
  "ingest-body-4": "数字码提交\n雷达求两圆交点",
  "ingest-dedup-title": "时间控制",
  "ingest-dedup-body": "default 全天 / custom 时段",
  "ingest-state-title": "防风控",
  "ingest-state-body": "达到 answer_threshold 后才提交",
  "ingest-comp-title": "可观察",
  "ingest-comp-body": "SSE 回传巡航与签到结果",
});

rewrite(12, {
  "kicker-5": "11 · OJ 实现",
  "title-5": "OJ 托管把读取题目、生成代码、提交评测串成流水线",
  "footer-5": "12",
  "ingest-title-0": "建立会话",
  "ingest-body-0": "GET 首页取 CSRF\nPOST /api/login",
  "ingest-title-1": "进入实验",
  "ingest-body-1": "读取 contest\n密码实验再解锁",
  "ingest-title-2": "筛选题目",
  "ingest-body-2": "加载 problem\n跳过已通过题目",
  "ingest-title-3": "生成提交",
  "ingest-body-3": "模型生成代码\nPOST submission",
  "ingest-title-4": "轮询结果",
  "ingest-body-4": "按 submission_id\n轮询评测 / 冷却",
  "ingest-dedup-title": "模型适配",
  "ingest-dedup-body": "Gemini / OpenAI-compatible",
  "ingest-state-title": "流式反馈",
  "ingest-state-body": "EventSource 展示生成、提交与评测状态",
  "ingest-comp-title": "当前边界",
  "ingest-comp-body": "固定密码 / verify=False",
});

rewrite(13, {
  "kicker-8": "12 · Deadline 看板",
  "title-8": "Deadline 以“缓存秒开 + 手动同步”兼顾速度与新鲜度",
  "footer-8": "13",
  "desktop-title-0": "缓存优先",
  "desktop-body-0": "选择账号时请求 sync=false，直接按 deadline 从 SQLite 读取，页面立即展示。",
  "desktop-label-0": "日常打开",
  "desktop-title-1": "畅课同步",
  "desktop-body-1": "点击同步后用 xmulogin 登录，通过同一 Session 请求 /api/todos 并解析 todo_list。",
  "desktop-label-1": "需要刷新",
  "desktop-title-2": "落库与分级",
  "desktop-body-2": "先清旧数据再批量写入；前端按已逾期、24h、72h、时间充裕显示时间线颜色。",
  "desktop-label-2": "展示结果",
  "desktop-note": "统一课程、任务、类型、截止时间与提交状态；单条异常跳过，不阻塞同步。",
});

const exported = await PresentationFile.exportPptx(presentation);
await exported.save(output);
console.log(output);
