<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>智能化 Deadline 看板</title>
    <!-- 引入 Tailwind CSS 快速构建样式 -->
    <script src="https://cdn.tailwindcss.com"></script>
    <!-- 引入 Vue 3 进行数据绑定 -->
    <script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>
    <!-- 引入图标库 -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        /* 隐藏滚动条但保留滚动功能 */
        .no-scrollbar::-webkit-scrollbar { display: none; }
        .no-scrollbar { -ms-overflow-style: none; scrollbar-width: none; }
    </style>
</head>
<body class="bg-gray-50 h-screen overflow-hidden text-gray-800">

<div id="app" class="flex h-full max-w-7xl mx-auto bg-white shadow-xl overflow-hidden">
    
    <!-- ================= 左侧栏：账号管理 (对接 campus_assistant.db) ================= -->
    <div class="w-1/4 bg-gray-900 text-white flex flex-col">
        <div class="p-6 bg-gray-800 shadow-md">
            <h1 class="text-xl font-bold tracking-wider"><i class="fa-solid fa-graduation-cap mr-2"></i>Campus Assistant</h1>
            <p class="text-sm text-gray-400 mt-1">智能 Deadline 监控中心</p>
        </div>

        <!-- 账号列表 -->
        <div class="flex-1 overflow-y-auto no-scrollbar p-4">
            <div class="text-xs text-gray-400 font-semibold mb-3 uppercase">已认证账号 (Shared DB)</div>
            <ul>
                <li v-for="acc in accounts" :key="acc.id" 
                    @click="selectAccount(acc)"
                    class="p-3 mb-2 rounded-lg cursor-pointer transition-all duration-200 border border-transparent"
                    :class="selectedAccount?.id === acc.id ? 'bg-blue-600 border-blue-400 shadow-lg' : 'bg-gray-800 hover:bg-gray-700'">
                    <div class="flex items-center">
                        <div class="w-8 h-8 rounded-full bg-gray-600 flex items-center justify-center font-bold mr-3">
                            {{ acc.name.charAt(0) }}
                        </div>
                        <div>
                            <p class="font-medium text-sm">{{ acc.name }}</p>
                            <p class="text-xs text-gray-400">{{ acc.student_id }}</p>
                        </div>
                    </div>
                </li>
            </ul>
        </div>

        <!-- 添加账号按钮 -->
        <div class="p-4 bg-gray-800">
            <button @click="showAddAccountModal = true" class="w-full py-2 bg-gray-700 hover:bg-blue-600 text-sm font-medium rounded-lg transition-colors border border-gray-600">
                <i class="fa-solid fa-plus mr-1"></i> 添加统一身份认证
            </button>
        </div>
    </div>

    <!-- ================= 右侧栏：时间线内容 ================= -->
    <div class="flex-1 flex flex-col relative">
        
        <!-- 顶部导航 -->
        <div class="h-16 bg-white border-b border-gray-200 flex items-center px-8 justify-between shadow-sm z-10">
            <h2 class="text-lg font-bold text-gray-700">
                <span v-if="selectedAccount">正在查看: {{ selectedAccount.name }} 的任务线</span>
                <span v-else class="text-gray-400">请在左侧选择一个账号</span>
            </h2>
            
            <!-- 切换视图 Tab -->
            <div class="flex space-x-1 bg-gray-100 p-1 rounded-lg">
                <button @click="currentView = 'assignments'" 
                        :class="currentView === 'assignments' ? 'bg-white shadow text-blue-600' : 'text-gray-500 hover:text-gray-700'"
                        class="px-4 py-1.5 text-sm font-medium rounded-md transition-all">
                    <i class="fa-solid fa-code-branch mr-1"></i> 作业 / 小测
                </button>
                <button @click="currentView = 'exams'" 
                        :class="currentView === 'exams' ? 'bg-white shadow text-red-600' : 'text-gray-500 hover:text-gray-700'"
                        class="px-4 py-1.5 text-sm font-medium rounded-md transition-all">
                    <i class="fa-solid fa-file-signature mr-1"></i> 考试安排
                </button>
            </div>
        </div>

        <!-- 时间线主区域 -->
        <div class="flex-1 overflow-y-auto bg-gray-50 p-8">
            <div v-if="!selectedAccount" class="flex flex-col items-center justify-center h-full text-gray-400">
                <i class="fa-solid fa-ghost text-6xl mb-4 opacity-50"></i>
                <p>暂无数据，请先选择账号</p>
            </div>

            <!-- 视图 1：作业时间线 (垂直自上而下) -->
            <div v-if="selectedAccount && currentView === 'assignments'" class="max-w-3xl mx-auto relative">
                <!-- 垂直基准线 -->
                <div class="absolute left-32 top-0 bottom-0 w-0.5 bg-gray-200"></div>

                <div v-for="item in assignments" :key="item.id" class="relative flex items-start mb-8 group">
                    <!-- 左侧具体时间 (月.日.时.分.秒) -->
                    <div class="w-28 text-right pr-6 pt-1">
                        <p class="text-sm font-bold text-gray-700">{{ formatMonthDay(item.deadline) }}</p>
                        <p class="text-xs text-gray-500">{{ formatTime(item.deadline) }}</p>
                    </div>

                    <!-- 时间轴圆点 -->
                    <div class="absolute left-32 w-3 h-3 bg-blue-500 rounded-full border-4 border-white shadow -translate-x-1.5 mt-1.5 group-hover:bg-blue-600 transition-colors"></div>

                    <!-- 右侧内容卡片 -->
                    <div class="flex-1 pl-8">
                        <div class="bg-white p-4 rounded-xl shadow-sm border border-gray-100 hover:shadow-md transition-shadow cursor-pointer" @click="viewDetails(item)">
                            <div class="flex justify-between items-start mb-1">
                                <span class="text-xs font-bold px-2 py-1 bg-blue-50 text-blue-600 rounded">{{ item.course }}</span>
                                <span :class="getStatusColor(item.deadline)" class="text-xs font-medium">{{ getStatusText(item.deadline) }}</span>
                            </div>
                            <h3 class="text-md font-bold text-gray-800 mt-2">{{ item.title }}</h3>
                        </div>
                    </div>
                </div>
            </div>

            <!-- 视图 2：考试安排 (列表卡片带跳转) -->
            <div v-if="selectedAccount && currentView === 'exams'" class="max-w-4xl mx-auto grid grid-cols-1 md:grid-cols-2 gap-4">
                <div v-for="exam in exams" :key="exam.id" class="bg-white rounded-xl shadow-sm border border-red-100 p-5 hover:border-red-300 transition-colors">
                    <div class="flex items-center justify-between border-b border-gray-100 pb-3 mb-3">
                        <h3 class="text-lg font-bold text-gray-800"><i class="fa-regular fa-clock text-red-500 mr-2"></i>{{ exam.course }}</h3>
                        <span class="text-xs bg-red-50 text-red-600 px-2 py-1 rounded border border-red-200">期末考试</span>
                    </div>
                    <div class="space-y-2 text-sm text-gray-600 mb-4">
                        <p><strong>时间：</strong>{{ exam.time_str }}</p>
                        <p><strong>地点：</strong>{{ exam.location }}</p>
                    </div>
                    <a :href="exam.link" target="_blank" class="block text-center w-full py-2 bg-red-50 hover:bg-red-100 text-red-600 font-medium rounded-lg transition-colors text-sm">
                        <i class="fa-solid fa-link mr-1"></i> 前往教务处查看通知
                    </a>
                </div>
            </div>

        </div>
    </div>

    <!-- 弹窗：添加账号 (隐藏状态，仅作占位示意) -->
    <div v-if="showAddAccountModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
        <div class="bg-white p-6 rounded-xl w-96 shadow-2xl">
            <h2 class="text-xl font-bold mb-4">添加学校账号</h2>
            <input type="text" placeholder="学号" class="w-full border p-2 rounded mb-3 bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500">
            <input type="password" placeholder="密码" class="w-full border p-2 rounded mb-4 bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500">
            <div class="flex justify-end space-x-2">
                <button @click="showAddAccountModal = false" class="px-4 py-2 text-gray-500 hover:bg-gray-100 rounded">取消</button>
                <button @click="showAddAccountModal = false" class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 shadow">验证并保存</button>
            </div>
        </div>
    </div>

</div>

<script>
    const { createApp, ref, computed } = Vue;

    createApp({
        setup() {
            const showAddAccountModal = ref(false);
            const currentView = ref('assignments'); // 'assignments' or 'exams'
            const selectedAccount = ref(null);

            // Mock 账号数据，实际应调用 GET /api/accounts，读取 campus_assistant.db
            const accounts = ref([
                { id: 1, name: '李同学', student_id: '229202xxx' },
                { id: 2, name: '张同学', student_id: '229202yyy' }
            ]);

            // Mock 作业数据
            const assignments = ref([
                { id: 101, course: '计算机组成原理', title: 'Cache 命中率计算作业', deadline: '2026-05-10T23:59:59' },
                { id: 102, course: '数据结构与算法', title: '红黑树插入删除验证实验', deadline: '2026-05-15T22:00:00' },
                { id: 103, course: '概率论与数理统计', title: '第五章 假设检验课后题', deadline: '2026-05-18T12:00:00' },
            ]);

            // Mock 考试数据
            const exams = ref([
                { id: 201, course: '微积分 (下)', time_str: '2026-06-25 09:00 - 11:00', location: '翔安校区 庄汉水楼 301', link: 'https://jwc.xmu.edu.cn/notice/1' },
                { id: 202, course: 'C++ 程序设计', time_str: '2026-06-28 14:30 - 16:30', location: '翔安校区 航空航天大楼 机房A', link: 'https://jwc.xmu.edu.cn/notice/2' }
            ]);

            const selectAccount = (acc) => {
                selectedAccount.value = acc;
                // 实际开发中，这里应当触发一个 API 请求获取该账号的 deadline：
                // fetch(`/api/campus/deadlines?student_id=${acc.student_id}`).then(...)
            };

            // 格式化时间为 月.日
            const formatMonthDay = (dateStr) => {
                const d = new Date(dateStr);
                return `${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getDate()).padStart(2, '0')}`;
            };

            // 格式化时间为 时:分:秒
            const formatTime = (dateStr) => {
                const d = new Date(dateStr);
                return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
            };

            // 防破防提醒逻辑：根据剩余时间返回不同的紧急程度状态
            const getStatusText = (dateStr) => {
                const ddl = new Date(dateStr).getTime();
                const now = new Date().getTime();
                const diffHours = (ddl - now) / (1000 * 60 * 60);

                if (diffHours < 0) return '已逾期';
                if (diffHours < 24) return '极度紧急 (不足24h)';
                if (diffHours < 72) return '即将截止 (不足3天)';
                return '时间充裕';
            };

            const getStatusColor = (dateStr) => {
                const text = getStatusText(dateStr);
                if (text === '已逾期') return 'text-gray-400';
                if (text.includes('极度紧急')) return 'text-red-600 font-bold animate-pulse';
                if (text.includes('即将截止')) return 'text-orange-500';
                return 'text-green-500';
            };

            const viewDetails = (item) => {
                alert(`查看详情：${item.course} - ${item.title}`);
                // 这里可以展开一个侧边抽屉展示作业要求，或跳转到 TronClass
            };

            return {
                accounts,
                selectedAccount,
                currentView,
                assignments,
                exams,
                showAddAccountModal,
                selectAccount,
                formatMonthDay,
                formatTime,
                getStatusText,
                getStatusColor,
                viewDetails
            };
        }
    }).mount('#app');
</script>
</body>
</html>