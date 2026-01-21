# 基于大模型生成PTG的HarmonyOS应用自动化测试

## 数据集（被测应用）
- HarmoneyOpenEye: https://github.com/WinWang/HarmoneyOpenEye
- Harmony-arkts-movie-music-app-ui: https://github.com/wuyuanwuhui99/Harmony-arkts-movie-music-app-ui
- biandan-satge: https://github.com/AlthenWaySatan/biandan-satge
- ArkTS-wphui1.0: https://gitee.com/boring-music/ArkTS-wphui1.0
- MultiShopping: https://gitee.com/harmonyos/codelabs/tree/master/MultiShopping
- MultiDeviceMusic: https://gitee.com/harmonyos/codelabs/tree/master/MultiDeviceMusic

克隆数据集，例如：
```bash
python clone_projects.py E:/HarmonyOS
```

## baseline
基于模型的HarmonyOS应用自动化测试的复现结果（与原作者的论文的结果有些出入，一些指标与原作者的论文有差异）：https://github.com/sqlab-sustech/HarmonyOS-App-Test

通过静态解析生成的PTG详见/static_analysis

## 环境
- Python 3.10.4
- 安装依赖：
```bash
pip install -r requirements.txt
```

## 纯LLM交互

### prompt内容
prompt都由一下三部分组成：
1. 全局Prompt：包含项目的全局信息，如项目结构、组件库等。
2. 任务Prompt：包含具体的任务描述，如添加新页面、修改组件属性等。
3. 限制性Prompt：用于限制模型生成的代码范围，如只生成路由/导航相关的代码。

### 执行方式
```bash
py llm/llm_server.py --deepseek --HarmoneyOpenEye
```

### 待解决/探究的问题  
1. 海外的大模型怎么搞
2. 国内的大模型，DeepSeek目前效果还挺好的，但是其他模型效果不好，考虑不同的模型使用不同的prompt，或换模型（Qwen, Kimi）
3. Harmony-arts-movie-music-app-ui项目，静态解析pages/IndexPage.ets文件的结果，代码中没有显示的路由跳转规则，但通过静态解析仍然能解析出，同时其他页面的一些跳转关系，通过静态解析无法解析出来（例如：pages/RegisterPage.ets等），但原作者仍然将其FNR率统计和计算为0%。
4. MutliShopping该项目与其他项目的结构不同，提取了common模块，在解析和组装prompt可能存在影响，考虑更换其他数据集或调整解析逻辑。
5. 生成的PTG存在不稳定（需要后续添加Agent工作流进行校验和修正）

## RAG+Agent增强版本（重构代码，与之前的纯LLM做对比）

### RAG
1. 知识补充：HarmonyOS应用相关文档，补充AI ArkTS相关的知识，识别PTG中与路由跳转相关的逻辑。
2. 校验和修正：根据生成的PTG中的跳转关系，喂入相关的文件，进行校验（文件级索引和片段级索引）。

待实现，目前觉得不是很有必要。

### Multi-Agent
工作流：读取项目代码->提取路由逻辑->生成跳转图->规则校验->修复（循环）

目前采用双Agent架构:
1. RouteExtractionAgent
	- 探索项目结构
	- 读取代码
	- 识别路由/跳转逻辑
	- 产出结构化路由数据
2. RouteGraphAgent
	- 根据结构化路由生成跳转图
	- 哪些页面路径需要“代码级回溯校验”
	- 校验是否符合规则
	- 如果不符合 -> 修复图
	- 控制 校验<-->修复 的关系

Tool设计：
1. RouteExtractionAgent
	- list_project_file: 探索项目结构，帮助Agent判断技术栈和关键目录
	- read_source_file: 读取指定代码文件内容
	- search_navigation_patterns: 在项目中搜索“疑似路由跳转相关代码”
2. RouteGraphAgent
	- build_route_graph: 将结构化路由数据->跳转图表示
	- validate_graph_structure: 校验图是否满足结构性规则
	- validate_route_against_code: 逐条边回溯代码，确认跳转是否真实/有条件
	- fix_route: 根据错误信息修复跳转图

### 执行方式
