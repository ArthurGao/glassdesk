import { expect, test } from '@playwright/test'

test('a rated answer shows up in insights, with the KB gaps labelled as demo data', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('用户名').fill('e2e-admin')
  await page.getByLabel('密码').fill('e2e-password')
  await page.getByRole('button', { name: '登录' }).click()

  await page.getByRole('button', { name: '+ 新会话' }).click()
  await page.getByLabel('问题').fill('出差住宿上限是多少？')
  await page.getByRole('button', { name: '发送' }).click()
  const helpful = page.getByRole('button', { name: '有帮助' }).last()
  await expect(helpful).toBeVisible()
  await helpful.click()
  await expect(helpful).toHaveAttribute('aria-pressed', 'true')

  await page.getByRole('link', { name: '洞察' }).click()
  const tiles = page.getByRole('list', { name: '概览' })
  await expect(tiles.getByText('好评率').locator('xpath=following-sibling::div')).toContainText('%')
  await expect(page.getByText('演示数据')).toBeVisible()
  await expect(page.getByText('海外差旅住宿标准')).toBeVisible()
})
