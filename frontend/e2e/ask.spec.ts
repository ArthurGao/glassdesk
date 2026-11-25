import { expect, test } from '@playwright/test'

test('ask a question: the timeline shows each step, the citation opens its passage', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)
  await page.getByLabel('用户名').fill('e2e-admin')
  await page.getByLabel('密码').fill('e2e-password')
  await page.getByRole('button', { name: '登录' }).click()

  await page.getByRole('button', { name: '+ 新会话' }).click()
  await page.getByLabel('问题').fill('出差住宿上限是多少？')
  await page.getByRole('button', { name: '发送' }).click()

  const timeline = page.getByRole('complementary', { name: '执行过程' })
  await expect(timeline.getByText('成本 未知')).toBeVisible()
  await expect(timeline.locator('li > div > div:first-child')).toHaveText([
    '问题',
    '分析问题',
    '搜索知识库',
    '生成回答',
    '完成',
  ])
  await expect(timeline.getByText('“出差住宿上限是多少？” → 2 条')).toBeVisible()

  await expect(page.getByText('根据《差旅制度 v3》')).toBeVisible()
  await page.getByRole('button', { name: '[1]' }).click()
  const popover = page.getByRole('dialog', { name: '引用 1' })
  await expect(popover).toContainText('国内出差住宿上限每晚 800 元')
  await expect(popover).toContainText('已验证')
  await expect(page.getByRole('button', { name: '发送' })).toBeDisabled() // empty, not busy
  await page.getByLabel('问题').fill('再问一个')
  await expect(page.getByRole('button', { name: '发送' })).toBeEnabled()
})
