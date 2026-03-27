import hilog from '@ohos.hilog';
import { Driver, ON } from '@ohos.UiTest'
import router from '@ohos.router';
import { PTGItem } from './type';

export class ModelTest {
  driver: Driver
  PTG: Map<string, Array<PTGItem>>
  vis: Set<string>
  vis_url: Set<string>

  count: number
  targetHitCount: Map<string, number>
  targetHitSet: Set<string>

  constructor(driver: Driver, PTG: Map<string, Array<PTGItem>>) {
    this.driver = driver;
    this.PTG = PTG;
    this.vis = new Set<string>();
		this.vis_url = new Set<string>();
    this.count = 0;
    this.targetHitCount = new Map<string, number>();
    this.targetHitSet = new Set<string>();
  }

  private groupChildrenByType(children: Array<PTGItem>): Map<string, Array<{ event: string, target: string }>> {
    const grouped = new Map<string, Array<{ event: string, target: string }>>();
    for (let { component: { type }, event, target } of children) {
      const current = grouped.get(type) || [];
      current.push({ event, target });
      grouped.set(type, current);
    }
    return grouped;
  }

  private recordTargetHit(target: string) {
    this.targetHitCount.set(target, (this.targetHitCount.get(target) || 0) + 1);
    this.targetHitSet.add(target);
  }

  private isSameBounds(a, b): boolean {
    return a.left === b.left && a.right === b.right && a.top === b.top && a.bottom === b.bottom;
  }

  private getCurrentPage(): string {
    const basePage = router.getState().path + router.getState().name;
    try {
      const params = router.getParams();
      if (params && typeof params === 'object') {
        const entries: Array<string> = [];
        const keys = Object.keys(params).sort();
        for (let key of keys) {
          const value = params[key];
          if (value === undefined || value === null || value === '') {
            continue;
          }
          const encodedKey = encodeURIComponent(key);
          const encodedValue = encodeURIComponent(typeof value === 'string' ? value : JSON.stringify(value));
          entries.push(`${encodedKey}=${encodedValue}`);
        }
        if (entries.length > 0) {
          return `${basePage}?${entries.join('&')}`;
        }
      }
    } catch (_) {
    }
    return basePage;
  }

  private async backToPage(targetPage: string, maxSteps: number = 5): Promise<boolean> {
    for (let i = 0; i < maxSteps; i++) {
      const page = this.getCurrentPage();
      if (page === targetPage) {
        return true;
      }
      if (!(typeof router.getLength === 'function' && parseInt(router.getLength()) > 1)) {
        break;
      }
      await this.driver.pressBack();
      await this.driver.delayMs(800);
    }
    return this.getCurrentPage() === targetPage;
  }

  private isBoundsClose(a, b, tolerance: number = 6): boolean {
    return Math.abs(a.left - b.left) <= tolerance &&
      Math.abs(a.right - b.right) <= tolerance &&
      Math.abs(a.top - b.top) <= tolerance &&
      Math.abs(a.bottom - b.bottom) <= tolerance;
  }

  private stripQuery(pageKey: string): string {
    const idx = pageKey.indexOf('?');
    return idx >= 0 ? pageKey.slice(0, idx) : pageKey;
  }

  private isPageMatchTarget(currentPage: string, targetPage: string): boolean {
    if (!targetPage) {
      return false;
    }
    // If target includes params/query, require full match.
    if (targetPage.indexOf('?') >= 0) {
      return currentPage === targetPage;
    }
    // If target has no params/query, compare by base page path.
    return this.stripQuery(currentPage) === targetPage;
  }

  private async isComponentInCurrentPage(component, type: string, originPage?: string): Promise<boolean> {
    if (originPage && this.getCurrentPage() !== originPage) {
      return false;
    }
    try {
      const targetBounds = await component.getBounds();
      const latestComponents = await this.driver.findComponents(ON.type(type));
      if (!latestComponents || !Array.isArray(latestComponents) || latestComponents.length === 0) {
        return false;
      }
      for (let latest of latestComponents) {
        try {
          const latestBounds = await latest.getBounds();
          if (this.isSameBounds(targetBounds, latestBounds) || this.isBoundsClose(targetBounds, latestBounds)) {
            return true;
          }
        } catch (_) {
        }
      }
      return false;
    } catch (_) {
      return false;
    }
  }

  async handleSafePressBack(router) {
    if (typeof router.getLength === 'function' && parseInt(router.getLength()) > 1) {
      hilog.info(0x0000, 'testTag', '%{public}s', `router stack length: ${router.getLength()}`);
      await this.driver.pressBack();
    }
  }

	private getBaseUrl(curPage: string): string {
		if (!curPage) {
			return '';
		}
		const idx = curPage.indexOf('?');
		return idx >= 0 ? curPage.slice(0, idx) : curPage;
	}


  async test(skipTabLoop: boolean = false) {
    let curPage = this.getCurrentPage();
    hilog.info(0x0000, 'testTag', '%{public}s', `curPage: ${curPage}`);
    if (this.vis.has(curPage)) {
      await this.driver.delayMs(1000);
      if (!skipTabLoop) {
        await this.handleSafePressBack(router)
      }
      await this.driver.delayMs(1000);
      return;
    }
    this.vis.add(curPage);
		this.vis_url.add(this.getBaseUrl(curPage));
    hilog.info(0x0000, 'testTag', '%{public}s', `currentPage: ${curPage}`);
    hilog.info(0x0000, 'testTag', '%{public}s', `pages vis_url: ${this.vis_url.size}`);
    const children = this.PTG.get(this.getBaseUrl(curPage)) || [];
    hilog.info(0x0000, 'testTag', '%{public}s', `children: ${JSON.stringify(children)}`);
    // if (children.length === 0) {
    //   return;
    // }
    const doAction = async () => {
      const actionPage = this.getCurrentPage();
      const actionChildren = this.PTG.get(this.getBaseUrl(actionPage)) || [];
      const groupedChildren = this.groupChildrenByType(actionChildren);
      hilog.info(0x0000, 'testTag', '%{public}s', `doAction page: ${actionPage}, grouped size: ${groupedChildren.size}`);
      for (let [type, actions] of groupedChildren) {
        let originPage = this.getCurrentPage();
        await this.driver.delayMs(2000);
        let components = await this.driver.findComponents(ON.type(type));
        hilog.info(0x0000, 'testTag', '%{public}s', `component type: ${type}, component: ${JSON.stringify(components)}`);
        if (components) {
          // const clickActions = actions.filter((item) => item.event === 'onClick');
          // if (clickActions.length === 0) {
          //   hilog.info(0x0000, 'testTag', '%{public}s', `skip type(no click action): ${type}`);
          //   continue;
          // }

          let executableComponents = [];
          let noClickCount = 0;
          for (let component of components) {
            if (typeof component.click !== 'function') {
              noClickCount++;
              continue;
            }
            executableComponents.push(component);
          }
          hilog.info(0x0000, 'testTag', '%{public}s', `filtered components: type=${type}, total=${components.length}, executable=${executableComponents.length}, noClick=${noClickCount}`);
          if (executableComponents.length === 0) {
            continue;
          }

          // if (type === 'ListItem' || type === 'GridItem') {
          //   executableComponents = [executableComponents[0]];
          // }
          let no = 0
          if (executableComponents.length > 20) {
            executableComponents = executableComponents.slice(0, 20)
          }
          hilog.info(0x0000, 'testTag', '%{public}s', `executable components: length=${executableComponents.length}`);
          for (let component of executableComponents) {
            no++;
            hilog.info(0x0000, 'testTag', '%{public}s', `component no: ${no}, component type: ${type}`);
            let page = this.getCurrentPage();
            if (page !== originPage) {
              const returned = await this.backToPage(originPage);
              if (!returned) {
                hilog.info(0x0000, 'testTag', '%{public}s', `break type loop: cannot return to originPage=${originPage}, currentPage=${this.getCurrentPage()}`);
                break;
              }
              page = this.getCurrentPage();
            }
            // while (page != originPage) {
            //   await this.test();
            //   page = router.getState().path + router.getState().name;
            // }
            try {
              await component.click();
              this.count++;
              hilog.info(0x0000, 'testTag', '%{public}s', `action count: ${this.count}`);
            } catch (err) {
              hilog.info(0x0000, 'testTag', '%{public}s', `click failed and skipped: type=${type}, err=${JSON.stringify(err)}`);
              continue;
            }
            await this.driver.delayMs(1000);
            page = this.getCurrentPage();
            const matchedAction = actions.find((item) => item.event === 'onClick' && this.getBaseUrl(page) === item.target);
            if (matchedAction) {
              this.recordTargetHit(matchedAction.target);
              hilog.info(0x0000, 'testTag', '%{public}s', `target hit: ${matchedAction.target}, count: ${this.targetHitCount.get(matchedAction.target)}, uniqueTarget: ${this.targetHitSet.size}`);
              hilog.info(0x0000, 'testTag', '%{public}s', `currentPage is target: ${page}`);
              await this.test(true);
            } else if (this.getBaseUrl(page) === originPage) {
              hilog.info(0x0000, 'testTag', '%{public}s', `currentPage is curPage: ${page}`);
              await this.driver.delayMs(1000);
            } else {
              hilog.info(0x0000, 'testTag', '%{public}s', `currentPage isn't target: ${page}`);
              // await this.test();
              // await this.driver.delayMs(1000);
              await this.handleSafePressBack(router);
            }
          }
        }
      }
    }

    const randomAction = async () => {
      for (let i = 0; i < 10; i++) {
        await this.componentClick();
        await this.driver.delayMs(1000);
        let page = this.getCurrentPage();
        if (!this.vis.has(page) && page !== curPage) {
          await this.test();
        }
      }
    }

    if (skipTabLoop) {
      await doAction();
    } else {
      let tabBars = await this.driver.findComponents(ON.type('TabBar'));
      if (tabBars) {
        for (let tabBar of tabBars) {
          let tabBarNum = 4;
          let bounds = await tabBar.getBounds();
          let left = bounds.left, right = bounds.right, top = bounds.top, bottom = bounds.bottom;
          let d = Math.round((right - left) / tabBarNum);
          for (let i = 1; i <= tabBarNum; i++) {
          // for (let i = tabBarNum; i > 0; i--) {
            await this.driver.delayMs(2000);
            await this.driver.click(i * d - 20, top);
            hilog.info(0x0000, 'testTag', '%{public}s', `tab: ${i}`);
            // 594, 2790
            await this.driver.delayMs(2000);
            await doAction();
            if (i == 4) {
              // await randomAction();
            }
          }
        }
      } else {
        await doAction();
        // await randomAction();
      }
    }
    await this.driver.delayMs(1000);
    await this.handleSafePressBack(router)
    await this.driver.delayMs(1000);
    hilog.info(0x0000, 'testTag', '%{public}s', `target hit summary: unique=${this.targetHitSet.size}, map=${JSON.stringify(Array.from(this.targetHitCount.entries()))}`);
  }

  async componentClick() {
    let enabledComponents = await this.driver.findComponents(ON.enabled(true));
    if (enabledComponents && Array.isArray(enabledComponents) && enabledComponents.length > 0) {
      while (true) {
        let component = enabledComponents[Math.floor(Math.random() * enabledComponents.length)];
        let bound = await component.getBounds();
        let type = await component.getType();
        if (type !== 'Image') {
          hilog.info(0x0000, 'testTag', '%{public}s', `action count: ${this.count}}`);
          await component.click();
          this.count++;
          hilog.info(0x0000, 'testTag', '%{public}s', `action count: ${this.count}}`);
          hilog.info(0x0000, 'testTag', '%{public}s', `click ${bound.left}, ${bound.top}, ${bound.right}, ${bound.bottom}`);
          break;
        }
      }
    }
  }

  async componentScrollToTop() {
    let enabledComponents = await this.driver.findComponents(ON.enabled(true));
    if (enabledComponents && Array.isArray(enabledComponents) && enabledComponents.length > 0) {
      let component = enabledComponents[Math.floor(Math.random() * enabledComponents.length)];
      let speed = Math.floor(Math.random() * (15000 - 200) + 200);
      await component.scrollToTop(speed);
      hilog.info(0x0000, 'testTag', '%{public}s', `scrollToTop speed: ${speed}`);
    }
  }

  async componentScrollToBottom() {
    let enabledComponents = await this.driver.findComponents(ON.enabled(true));
    if (enabledComponents && Array.isArray(enabledComponents) && enabledComponents.length > 0) {
      let component = enabledComponents[Math.floor(Math.random() * enabledComponents.length)];
      let speed = Math.floor(Math.random() * (15000 - 200) + 200);
      await component.scrollToBottom(speed);
      hilog.info(0x0000, 'testTag', '%{public}s', `scrollToBottom speed: ${speed}`);
    }
  }
}
