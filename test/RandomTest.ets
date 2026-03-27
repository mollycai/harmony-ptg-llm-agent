import { Driver, ON } from '@ohos.UiTest'
import router from '@ohos.router';
import hilog from '@ohos.hilog';

export class RandomTest {
  driver: Driver
  leftBound: number
  rightBound: number
  topBound: number
  bottomBound: number
  randomActions = [this.componentClick.bind(this), this.driverClick.bind(this)];

  constructor(driver: Driver, leftBound: number, rightBound: number, topBound: number, bottomBound: number) {
    this.driver = driver;
    this.leftBound = leftBound;
    this.rightBound = rightBound;
    this.topBound = topBound;
    this.bottomBound = bottomBound;
  }

  async test() {
    let vis = new Set();
    let count = 0;
    while (true) {
      let curPage = router.getState().path + router.getState().name;
      vis.add(curPage);
      await this.action();
      count++;
      await this.driver.delayMs(2000);
      hilog.info(0x0000, 'testTag', '%{public}s', `pages vis: ${vis.size}`);
      hilog.info(0x0000, 'testTag', '%{public}s', `count: ${count}`);
    }
  }

  async action() {
    let randomAction: Function = this.randomActions[Math.floor(Math.random() * this.randomActions.length)];
    hilog.info(0x0000, 'testTag', '%{public}s', `randomAction: ${randomAction.name}`);
    await randomAction();
  }

  async componentClick() {
    let enabledComponents = await this.driver.findComponents(ON.enabled(true));
    if (Array.isArray(enabledComponents) && enabledComponents.length > 0) {
      let component = enabledComponents[Math.floor(Math.random() * enabledComponents.length)];
      let bound = await component.getBounds();
      await component.click();
      hilog.info(0x0000, 'testTag', '%{public}s', `click ${bound.left}, ${bound.top}, ${bound.right}, ${bound.bottom}`);
    }
  }

  async componentDoubleClick() {
    let enabledComponents = await this.driver.findComponents(ON.enabled(true));
    if (Array.isArray(enabledComponents) && enabledComponents.length > 0) {
      let component = enabledComponents[Math.floor(Math.random() * enabledComponents.length)];
      let bound = await component.getBounds();
      await component.doubleClick();
      hilog.info(0x0000, 'testTag', '%{public}s', `doubleClick ${bound.left}, ${bound.top}, ${bound.right}, ${bound.bottom}`);
    }
  }

  async componentLongClick() {
    let enabledComponents = await this.driver.findComponents(ON.enabled(true));
    if (Array.isArray(enabledComponents) && enabledComponents.length > 0) {
      let component = enabledComponents[Math.floor(Math.random() * enabledComponents.length)];
      let bound = await component.getBounds();
      await component.longClick();
      hilog.info(0x0000, 'testTag', '%{public}s', `longClick ${bound.left}, ${bound.top}, ${bound.right}, ${bound.bottom}`);
    }
  }

  async componentScrollToTop() {
    let enabledComponents = await this.driver.findComponents(ON.enabled(true));
    if (Array.isArray(enabledComponents) && enabledComponents.length > 0) {
      let component = enabledComponents[Math.floor(Math.random() * enabledComponents.length)];
      let speed = Math.floor(Math.random() * (15000 - 200) + 200);
      await component.scrollToTop(speed);
      hilog.info(0x0000, 'testTag', '%{public}s', `scrollToTop speed: ${speed}`);
    }
  }

  async componentScrollToBottom() {
    let enabledComponents = await this.driver.findComponents(ON.enabled(true));
    if (Array.isArray(enabledComponents) && enabledComponents.length > 0) {
      let component = enabledComponents[Math.floor(Math.random() * enabledComponents.length)];
      let speed = Math.floor(Math.random() * (15000 - 200) + 200);
      await component.scrollToBottom(speed);
      hilog.info(0x0000, 'testTag', '%{public}s', `scrollToBottom speed: ${speed}`);
    }
  }

  async componentDragTo() {
    let enabledComponents = await this.driver.findComponents(ON.enabled(true));
    if (Array.isArray(enabledComponents) && enabledComponents.length > 1) {
      let i1 = Math.floor(Math.random() * enabledComponents.length);
      let i2 = i1;
      while (i1 == i2) {
        i2 = Math.floor(Math.random() * enabledComponents.length);
      }
      let c1 = enabledComponents[i1];
      let c2 = enabledComponents[i2];
      if (Math.random() < 0.5) {
        await c1.dragTo(c2);
      } else {
        await c2.dragTo(c1);
      }
      hilog.info(0x0000, 'testTag', '%{public}s', 'dragTo');
    }
  }

  async componentPinchIn() {
    let enabledComponents = await this.driver.findComponents(ON.enabled(true));
    if (Array.isArray(enabledComponents) && enabledComponents.length > 0) {
      let component = enabledComponents[Math.floor(Math.random() * enabledComponents.length)];
      let scale = Math.random() * 10;
      await component.pinchIn(scale);
      hilog.info(0x0000, 'testTag', '%{public}s', `pinchIn: ${scale}`);
    }
  }

  async componentPinchOut() {
    let enabledComponents = await this.driver.findComponents(ON.enabled(true));
    if (Array.isArray(enabledComponents) && enabledComponents.length > 0) {
      let component = enabledComponents[Math.floor(Math.random() * enabledComponents.length)];
      let scale = Math.random() * 10;
      await component.pinchOut(scale);
      hilog.info(0x0000, 'testTag', '%{public}s', `pinchOut: ${scale}`);
    }
  }

  async componentInputText() {

    function getRandomChineseWord() {
      let _rsl = "";
      let _randomUniCode = Math.floor(Math.random() * (40870 - 19968) + 19968).toString(16);
      eval("_rsl=" + '"\\u' + _randomUniCode + '"');
      return _rsl;
    }

    let inputTextComponents = await this.driver.findComponents(ON.type('TextInput'));
    if (Array.isArray(inputTextComponents) && inputTextComponents.length > 0) {
      let component = inputTextComponents[Math.floor(Math.random() * inputTextComponents.length)];
      let inputText;
      if (Math.random() < 0.5) {
        inputText = Math.random().toString(36).slice(-8);
      } else {
        inputText = getRandomChineseWord();
      }
      await component.inputText(inputText);
      hilog.info(0x0000, 'testTag', '%{public}s', `inputText: ${inputText}`);
    }
  }

  async componentClearText() {
    let inputTextComponents = await this.driver.findComponents(ON.type('TextInput'));
    if (Array.isArray(inputTextComponents) && inputTextComponents.length > 0) {
      let component = inputTextComponents[Math.floor(Math.random() * inputTextComponents.length)];
      let text = await component.getText();
      await component.clearText();
      hilog.info(0x0000, 'testTag', '%{public}s', `clearText: ${text}`);
    }
  }

  async driverClick() {
    let x = Math.floor(Math.random() * (this.rightBound - this.leftBound) + this.leftBound);
    let y = Math.floor(Math.random() * (this.bottomBound - this.topBound) + this.topBound);
    await this.driver.click(x, y);
    hilog.info(0x0000, 'testTag', '%{public}s', `driverClick: ${x}, ${y}`);
  }

  async driverDoubleClick() {
    let x = Math.floor(Math.random() * (this.rightBound - this.leftBound) + this.leftBound);
    let y = Math.floor(Math.random() * (this.bottomBound - this.topBound) + this.topBound);
    await this.driver.doubleClick(x, y);
    hilog.info(0x0000, 'testTag', '%{public}s', `driverDoubleClick: ${x}, ${y}`);
  }

  async driverLongClick() {
    let x = Math.floor(Math.random() * (this.rightBound - this.leftBound) + this.leftBound);
    let y = Math.floor(Math.random() * (this.bottomBound - this.topBound) + this.topBound);
    await this.driver.longClick(x, y);
    hilog.info(0x0000, 'testTag', '%{public}s', `driverLongClick: ${x}, ${y}`);
  }

  async driverSwipe() {
    let x1 = Math.floor(Math.random() * (this.rightBound - this.leftBound) + this.leftBound);
    let x2 = Math.floor(Math.random() * (this.rightBound - this.leftBound) + this.leftBound);
    let y1 = Math.floor(Math.random() * (this.bottomBound - this.topBound) + this.topBound);
    let y2 = Math.floor(Math.random() * (this.bottomBound - this.topBound) + this.topBound);
    let speed = Math.floor(Math.random() * (15000 - 200) + 200);
    await this.driver.swipe(x1, y1, x2, y2, speed);
    hilog.info(0x0000, 'testTag', '%{public}s', `driverSwipe: (${x1}, ${y1} -> ${x2}, ${y2})`);
  }

  async driverDrag() {
    let x1 = Math.floor(Math.random() * (this.rightBound - this.leftBound) + this.leftBound);
    let x2 = Math.floor(Math.random() * (this.rightBound - this.leftBound) + this.leftBound);
    let y1 = Math.floor(Math.random() * (this.bottomBound - this.topBound) + this.topBound);
    let y2 = Math.floor(Math.random() * (this.bottomBound - this.topBound) + this.topBound);
    let speed = Math.floor(Math.random() * (15000 - 200) + 200);
    await this.driver.drag(x1, y1, x2, y2, speed);
    hilog.info(0x0000, 'testTag', '%{public}s', `driverDrag: (${x1}, ${y1} -> ${x2}, ${y2})`);
  }

  async driverFling() {
    let x1 = Math.floor(Math.random() * (this.rightBound - this.leftBound) + this.leftBound);
    let x2 = Math.floor(Math.random() * (this.rightBound - this.leftBound) + this.leftBound);
    let y1 = Math.floor(Math.random() * (this.bottomBound - this.topBound) + this.topBound);
    let y2 = Math.floor(Math.random() * (this.bottomBound - this.topBound) + this.topBound);
    let stepLen = Math.min(Math.abs(x1 - x2), Math.abs(y1 - y2));
    let speed = Math.floor(Math.random() * (15000 - 200) + 200);
    await this.driver.fling({ x: x1, y: y1 }, { x: x2, y: y2 }, stepLen, speed);
    hilog.info(0x0000, 'testTag', '%{public}s', `driverDrag: (${x1}, ${y1} -> ${x2}, ${y2})`);
  }
}
