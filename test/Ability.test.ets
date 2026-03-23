import { describe, it, expect } from '@ohos/hypium';
import abilityDelegatorRegistry from '@ohos.app.ability.abilityDelegatorRegistry';
import { Driver, ON } from '@ohos.UiTest'
import UIAbility from '@ohos.app.ability.UIAbility';
import PTGJson from './PTG';
import { RandomTest } from './RandomTest';
import { ModelTest } from './ModelTest';
import { PTGItem } from './type';

const delegator: abilityDelegatorRegistry.AbilityDelegator = abilityDelegatorRegistry.getAbilityDelegator();
const bundleName = abilityDelegatorRegistry.getArguments().bundleName;

function sleep(time: number) {
	return new Promise<void>((resolve: Function) => setTimeout(resolve, time));
}

export default function abilityTest() {
	describe('ActsAbilityTest', () => {
		it('testUiExample', 0, async (done: Function) => {
			console.info("uitest: TestUiExample begin");

			await delegator.executeShellCommand(`aa start -d 0 -a EntryAbility -b ${bundleName}`)
				.then((result: abilityDelegatorRegistry.ShellCmdResult) => {
					console.info('Uitest, start ability finished:' + result)
				})
				.catch((err) => {
					console.info('Uitest, start ability failed: ' + err)
				})
			await sleep(3000);

			await delegator.getCurrentTopAbility().then((Ability: UIAbility) => {
				console.info("get top ability");
				expect(Ability.context.abilityInfo.name).assertEqual('EntryAbility');
			})

			let ptg = JSON.parse(PTGJson);

			const PTG = new Map();
			for (let [pageName, obj] of Object.entries(ptg)) {
				PTG.set(pageName, []);
				PTG.get(pageName).push(...obj as Array<PTGItem>);
			}

			let driver = Driver.create();
			await driver.delayMs(3000);
			const root = await driver.findComponent(ON.type('root'));
			const bound = await root.getBounds();
			const randomTest: RandomTest = new RandomTest(driver, bound.left, bound.right, bound.top, bound.bottom);
			const modelTest: ModelTest = new ModelTest(driver, PTG);
			// await randomTest.test();
			await modelTest.test();
			done();
		})
	})
}