import { expect, type Page, test } from '@playwright/test'

async function login(page: Page) {
  await page.goto('/login')
  await page.getByLabel('用户名').fill('e2e-admin')
  await page.getByLabel('密码').fill('e2e-password')
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL(/\/$|\/\?/)
}

test('the agent proposes, the user confirms, the knowledge page lists it', async ({ page }) => {
  const fact = `报销要在 ${Date.now() % 100000} 天内提交`
  await login(page)
  await page.getByRole('button', { name: '+ 新会话' }).click()
  await page.getByLabel('问题').fill(`记住：${fact}`)
  await page.getByRole('button', { name: '发送' }).click()

  const timeline = page.getByRole('complementary', { name: '执行过程' })
  await expect(timeline.getByText('提议存入知识库')).toBeVisible()
  const card = page.getByRole('region', { name: '要不要存进知识库？' }).filter({ hasText: fact })
  await expect(card).toHaveCount(1)
  await card.getByRole('button', { name: '存为团队知识' }).click()
  await expect(card).toHaveCount(0)

  await page.getByRole('link', { name: '知识库' }).click()
  const row = page.getByRole('row').filter({ hasText: fact })
  await expect(row).toContainText('生效')
})

test('a high-risk entry waits for review and a reviewer approves it', async ({ page }) => {
  const title = `价格表 ${Date.now() % 100000}`
  await login(page)
  await page.getByRole('link', { name: '知识库' }).click()
  await page.getByRole('button', { name: '新建条目' }).click()
  await page.getByLabel('标题').fill(title)
  await page.getByLabel('内容').fill('A 套餐每月 99 元')
  await page.getByRole('button', { name: '保存' }).click()
  await expect(page.getByRole('status')).toContainText('已提交审核')

  await page.getByRole('tab', { name: '待审核' }).click()
  const review = page.getByRole('row').filter({ hasText: title })
  await review.getByRole('button', { name: '批准' }).click()
  await expect(review).toHaveCount(0)

  await page.getByRole('tab', { name: '条目' }).click()
  await expect(page.getByRole('row').filter({ hasText: title })).toContainText('已验证')
})

test('a reviewer deprecates an entry after confirming in the dialog', async ({ page }) => {
  const title = `会议室规则 ${Date.now() % 100000}`
  await login(page)
  await page.getByRole('link', { name: '知识库' }).click()
  await page.getByRole('button', { name: '新建条目' }).click()
  await page.getByLabel('标题').fill(title)
  await page.getByLabel('内容').fill('单次最长 2 小时')
  await page.getByRole('button', { name: '保存' }).click()
  await expect(page.getByRole('status')).toContainText('已存入知识库')

  const row = page.getByRole('row').filter({ hasText: title })
  await expect(row).toContainText('生效')
  await row.getByRole('button', { name: '停用' }).click()
  const dialog = page.getByRole('dialog', { name: '停用这个条目？' })
  await expect(dialog).toContainText(title)
  await dialog.getByLabel('原因（可选）').fill('已过时')
  await dialog.getByRole('button', { name: '停用' }).click()
  await expect(dialog).toHaveCount(0)
  await expect(row).toContainText('已停用')
  await expect(row.getByRole('button', { name: '停用' })).toHaveCount(0)
})
