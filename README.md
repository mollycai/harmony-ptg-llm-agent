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

## 环境与配置
- Python 3.10.4
- 安装依赖
```bash
pip install -r requirements.txt
```
- LLM API key
创建.env文件，添加如以下内容：
```bash
OPENAI_API_KEY=sk-xxxx
```
- 在config.py中填写对应的大模型配置，例如：
```python
LLM_CONFIG = {  
  "deepseek": {
    "baseURL": 'https://api.deepseek.com',
    "apiKeyEnv": 'DEEPSEEK_API_KEY', // 需要自己在根目录添加.env文件存放API KEY
    "model": 'deepseek-chat', // 最终交互的模型
    "preprocessModel": 'deepseek-chat', // 预处理项目代码的模型
  }
}
```
- 在config.py中填写对应的被测应用配置，例如：
```python
APP_CONFIG = {
  "HarmoneyOpenEye": {
    "projectName": "HarmoneyOpenEye",  # 项目名称
    "projectPath": "E:/HarmonyOS/project/HarmoneyOpenEye",  # 项目路径
    "projectMainPagePath":
      "E:/HarmonyOS/project/HarmoneyOpenEye/entry/src/main/resources/base/profile/main_pages.json",  # 项目主页面路径
  },
}
``` 

## 纯LLM交互

### prompt内容
prompt都由一下三部分组成：
1. 全局Prompt：包含项目的全局信息，如项目结构、组件库等。
2. 任务Prompt：包含具体的任务描述，如添加新页面、修改组件属性等。
3. 限制性Prompt：用于限制模型生成的代码范围，如只生成路由/导航相关的代码。

### 执行方式
```bash
py llm/workflow.py --deepseek --HarmoneyOpenEye
```

### 待解决/探究的问题    
1. 海外的大模型怎么搞
2. 国内的大模型，DeepSeek目前效果还挺好的，但是其他模型效果不好，考虑不同的模型使用不同的prompt，或换模型（Qwen, Kimi）
3. Harmony-arts-movie-music-app-ui项目，静态解析pages/IndexPage.ets文件的结果，代码中没有显示的路由跳转规则，但通过静态解析仍然能解析出，同时其他页面的一些跳转关系，通过静态解析无法解析出来（例如：pages/RegisterPage.ets等），但原作者仍然将其FNR率统计和计算为0%。
4. MutliShopping该项目与其他项目的结构不同，提取了common模块，在解析和组装prompt可能存在影响，考虑更换其他数据集或调整解析逻辑。
5. 生成的PTG存在不稳定（需要后续添加Agent工作流进行校验和修正）

## RAG & Agent增强版本（重构代码，与之前的纯LLM做对比）

### RAG
1. 知识补充：HarmonyOS应用相关文档，补充AI ArkTS相关的知识，识别PTG中与路由跳转相关的逻辑。
2. 校验和修正：根据生成的PTG中的跳转关系，喂入相关的文件，进行校验（文件级索引和片段级索引）。

待实现，目前觉得不是很有必要。

### Multi-Agent（实现中）
采用langChain搭建多Agent工作流，实现自动化测试。
工作流：读取项目代码->提取路由逻辑->生成跳转图->规则校验->回读代码->修复（循环至最大执行步数，例如3）

PTG schema: 
	```ts
		type PTG = Record<PagePath, Array<{
			component: {
				type: string;
			};
			event: string;
			target: string;
		}>>
	```

目前采用双Agent架构 :
1. RouteStructureAgent
	- 读取项目mainPages.json文件（获取项目的主页面）
	- 生成 PTG (Page Transition Graph) 的框架，例如：{ "pages/MainPage.ets": [], "pages/DetailPage.ets": [] ...}，这个json对象的键都是mainPages的路径，值都是空数组。并在这个工作流中一直维护这个PTG对象。
	- 根据这些主页面，读取对应页面文件的代码，如果发现嵌套的组件，例如pages/MainPage.ets中嵌套了pages/HomePage.ets，那么就需要递归地读取pages/HomePage.ets的代码，查找其中的路由跳转逻辑，注意代码开头导入的文件。如果发现路由跳转逻辑，则添加到PTG中对应主页面的数组中。
	- 遍历+递归地处理所有主页面，直到没有新的跳转逻辑被发现。
2. RouteValidationAgent
	- 校验PTG是否符合规则，检查：
		1. 每个主页面路径是否存在跳转逻辑（即数组非空）
		2. 每个跳转关系对应的组件和事件是否正确
		3. 是否符合输出的PTG schema
	- 定位到原项目代码中对应的跳转逻辑，回读代码，确认是否符合规则。
	- 如果发现错误，修正原来生成的PTG。

难点：  
1. 如何让agent读懂项目代码，特别是精准触发跳转逻辑的组件类型
2. 对于嵌套组件，如何准确识别跳转的目标，例如，pages/MainPage.ets中的代码，明面上没有与路由跳转有关的代码，但是其中嵌套着一些组件，例如pages/HomePage.ets，这个组件中则包含跳转到pages/DetailPage.ets的逻辑，则期望输出的跳转关系是pages/MainPage.ets -> pages/DetailPage.ets。这里可能涉及到上下文管理的问题，如果在每次交互中，只维护PTG，不维护项目代码的上下文，遇到一些import之类的语句（引入组件），大模型会忘记子组件与当前页面的关系；如果将整个项目上下文喂给大模型，则会出现上下文过长，产生幻觉的问题。目前的想法：全程维护PTG，同时让大模型只记住与一个主页面关联的代码上下文，当大模型开始探索下个主页面的代码时，则忘记上一个的上下文（主页面之间不会相互嵌套，不会出现一个主页面的代码中import另一个主页面，只是保留着路由跳转的关系，例如：一个主页面，跳转到另一个主页面）。
