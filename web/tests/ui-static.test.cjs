/** 工单 23 AC-UX-01 静态证据：全部可见按钮必须有真实行为或显式禁用 */
const { test } = require('node:test')
const assert = require('node:assert')
const fs = require('node:fs')
const path = require('node:path')

function walk(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) walk(full, out)
    else if (entry.name.endsWith('.tsx') || entry.name.endsWith('.ts')) out.push(full)
  }
  return out
}

test('no empty onClick handlers', () => {
  const files = walk(path.join(__dirname, '..', 'src'))
  for (const file of files) {
    const source = fs.readFileSync(file, 'utf-8')
    assert.ok(!/onClick=\{\(\) => \{\}\}/.test(source), `${file} 含空 onClick`)
  }
})

test('disabled primary actions are explicitly marked unavailable', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'src', 'components', 'PageBits.tsx'), 'utf-8')
  assert.ok(/该操作尚未开放/.test(source), 'PrimaryAction 必须为无 onClick 的动作提供显式不可用状态')
})
