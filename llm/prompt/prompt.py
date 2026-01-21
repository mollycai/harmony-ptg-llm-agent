GLOBAL_PROMPT = (
    "You are analyzing a HarmonyOS ArkTS app <N>. Main pages list: <X>. "
    "Only these paths are valid PTG keys and valid navigation targets."
)

TASK_PROMPT = """1. You will receive a Context JSON: keys are folder/file names, values are ArkTS source code.
2. Find ALL page navigation relationships by locating router navigation calls (e.g., router.push/router.replace, Router.push, pushUrl, back, and similar wrappers).
  2.1. Import resolution (CRITICAL): when a code value contains local imports (e.g., import { HomePage } from './home/HomePage'), you MUST use the Context JSON tree to locate the referenced file and read its value (code) to continue analysis. Resolve relative paths based on the importing file’s directory.
3. For each navigation event:
   a. Key must be the ROOT main page (must be in the main pages list) that contains the navigation trigger or instantiates the component path that leads to it.
   b. component.type is the UI component that triggers the event (e.g., ListItem, Button). If the trigger is inside a nested/custom component instantiated by a main page, use { type: '__Common__' }.
   c. event is the event name (e.g., onClick).
   d. target must be the FULL target main page path (must be in the main pages list).
4. Simple example: In 'ContainerPage.ets', 'ListItem{}.onClick(() => { Router.push(RouterPath: DetailPage) })' means:
   - Key: 'pages/container/ContainerPage' (the page in the main pages)
   - Component: { type: 'ListItem' } (the component directly triggering the event)
   - Event: 'onClick' (the event that triggers navigation)
   - Target: 'pages/commonDetail/DetailPage' (the full path of the target main page)
5. Complex example, the situation of nested componend: In 'MainPage.ets': 'import { HomePage } from './home/HomePage'; ... TabContent() { HomePage()}', you should find the 'HomePage' component througth the path, and continue analysis, for example, the 'HomePage.ets': ListItem() { HomeListItemComponent({ item: item }).onClick(() => { Router.push(RoutePath.DetailPage) }) }, means:
	 - Key: 'pages/MainPage' (the page in the main pages)
	 - Component: { type: '__Common__' } (if the component is not a custom component, then it is '__Common__')
	 - Event: 'onClick' (the event that triggers navigation)
	 - Target: 'pages/commonDetail/DetailPage' (the full path of the target main page)
6. Context JSON: <X>
7. Output the complete PTG JSON.
"""

RESTRICTIVE_PROMPT = """Output rules:
1. Output ONLY a single valid JSON object: { "pages/...": [ ... ], ... }.
2. Keys MUST be exactly and only the main pages list <X>.
3. Each value is an array of: { "component": { "type": "..." }, "event": "...", "target": "..." }.
4. target MUST be a main page path from <X>.
5. Do not output any extra text outside JSON."""