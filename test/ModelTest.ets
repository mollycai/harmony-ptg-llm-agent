import hilog from '@ohos.hilog';
import { Driver, ON } from '@ohos.UiTest'
import router from '@ohos.router';
import { PTGItem } from './type';

export class ModelTest {
  driver: Driver
  PTG: Map<string, Array<PTGItem>>
  vis: Set<string>
  count: number
  targetHitCount: Map<string, number>
  targetHitSet: Set<string>

  constructor(driver: Driver, PTG: Map<string, Array<PTGItem>>) {
    this.driver = driver;
    this.PTG = PTG;
    this.vis = new Set<string>();
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
    return router.getState().path + router.getState().name;
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

  async test() {
    let curPage = router.getState().path + router.getState().name;
    if (this.vis.has(curPage)) {
      await this.driver.delayMs(1000);
      await this.handleSafePressBack(router)
      await this.driver.delayMs(1000);
      return;
    }
    this.vis.add(curPage);
    hilog.info(0x0000, 'testTag', '%{public}s', `currentPage: ${curPage}`);
    hilog.info(0x0000, 'testTag', '%{public}s', `pages vis: ${this.vis.size}`);
    const children = this.PTG.get(curPage) || [];
    hilog.info(0x0000, 'testTag', '%{public}s', `children: ${JSON.stringify(children)}`);
    // if (children.length === 0) {
    //   return;
    // }
    const doAction = async () => {
      const groupedChildren = this.groupChildrenByType(children);
      for (let [type, actions] of groupedChildren) {
        let originPage = this.getCurrentPage();
        let components = await this.driver.findComponents(ON.type(type));
        hilog.info(0x0000, 'testTag', '%{public}s', `component type: ${type}, component: ${JSON.stringify(components)}, actions: ${JSON.stringify(actions)}`);
        if (components) {
          // if (type === 'ListItem' || type === 'GridItem' || type === '__Common__' || type === 'Stack') {
          //   components = [components[0]];
          // }
          let no = 0
          for (let component of components) {
            no++;
            hilog.info(0x0000, 'testTag', '%{public}s', `component no: ${no}`);
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
            if (typeof component.click === 'function') {
              const clickActions = actions.filter((item) => item.event === 'onClick');
              if (clickActions.length === 0) {
                continue;
              }
              const existsInCurrentPage = await this.isComponentInCurrentPage(component, type, originPage);
              if (!existsInCurrentPage) {
                hilog.info(0x0000, 'testTag', '%{public}s', `skip stale component: type=${type}, page=${router.getState().path + router.getState().name}`);
                continue;
              }
              try {
                await component.click();
                this.count++;
                hilog.info(0x0000, 'testTag', '%{public}s', `action count: ${this.count}`);
              } catch (err) {
                hilog.info(0x0000, 'testTag', '%{public}s', `click failed and skipped: type=${type}, err=${JSON.stringify(err)}`);
                continue;
              }
            }
            await this.driver.delayMs(1000);
            page = this.getCurrentPage();
            const matchedAction = actions.find((item) => item.event === 'onClick' && item.target === page);
            if (matchedAction) {
              this.recordTargetHit(matchedAction.target);
              hilog.info(0x0000, 'testTag', '%{public}s', `target hit: ${matchedAction.target}, count: ${this.targetHitCount.get(matchedAction.target)}, uniqueTarget: ${this.targetHitSet.size}`);
              hilog.info(0x0000, 'testTag', '%{public}s', `currentPage is target: ${router.getState().path + router.getState()
                .name}`);
              await this.test();
            } else if (page === originPage) {
              hilog.info(0x0000, 'testTag', '%{public}s', `currentPage is curPage: ${router.getState().path + router.getState()
                .name}`);
              await this.driver.delayMs(1000);
            } else {
              hilog.info(0x0000, 'testTag', '%{public}s', `currentPage isn't target: ${router.getState().path + router.getState()
                .name}`);
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
        let page = router.getState().path + router.getState().name;
        if (!this.vis.has(page) && page !== curPage) {
          await this.test();
        }
      }
    }

    let tabBars = await this.driver.findComponents(ON.type('TabBar'));
    if (tabBars) {
      for (let tabBar of tabBars) {
        let tabBarNum = 4;
        let bounds = await tabBar.getBounds();
        let left = bounds.left, right = bounds.right, top = bounds.top, bottom = bounds.bottom;
        let d = Math.round((right - left) / tabBarNum);
        for (let i = 4; i > 0; i--) {
          await this.driver.click(i * d - 20, top);

          await this.driver.delayMs(1000);
          await doAction();
          if (i == 4) {
            // await randomAction();
          }
        }
        // for (let i = 1; i <= tabBarNum; i++) {
        //   await this.driver.click(i * d - 20, top);
        //
        //   await this.driver.delayMs(2000);
        //   await doAction();
        //   if (i == 4) {
        //     // await randomAction();
        //   }
        // }
      }
    } else {
      await doAction();
      // await randomAction();
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
