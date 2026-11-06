// 查询缓存键必须包含项目范围：否则切换项目后，键不变，react-query 不会重取，
// 页面继续展示上一个项目的数据（工单 05 的规则见 store/effectiveContext.tsx scopeKey）。
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const ts = require('typescript')

const ROOTS = ['src/pages', 'src/components']

function sourceFiles() {
  const files = []
  for (const root of ROOTS) {
    const dir = path.join(__dirname, '..', root)
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.isFile() && /\.(tsx|ts)$/.test(entry.name)) files.push(path.join(dir, entry.name))
    }
  }
  return files
}

// 用 TS AST 只看 useQuery({...}) 的对象字面量：queryFn 引用 ctx.projectId 时，
// queryKey 必须也带 projectId。字符串/距离匹配会被相邻代码误导，所以走语法树。
function scopedKeyProblems(source, fileName) {
  const sourceFile = ts.createSourceFile(
    fileName, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX,
  )
  const problems = []
  const visit = node => {
    if (ts.isCallExpression(node) && node.expression.getText(sourceFile) === 'useQuery') {
      const options = node.arguments[0]
      if (options && ts.isObjectLiteralExpression(options)) {
        let keyText = null
        let fnText = ''
        for (const property of options.properties) {
          if (!ts.isPropertyAssignment(property)) continue
          const name = property.name.getText(sourceFile)
          if (name === 'queryKey') keyText = property.initializer.getText(sourceFile)
          if (name === 'queryFn') fnText = property.initializer.getText(sourceFile)
        }
        if (keyText && /\bctx\.projectId\b/.test(fnText) && !/projectId/.test(keyText)) {
          problems.push(keyText)
        }
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(sourceFile)
  return problems
}

test('UiPage 的资源与套件查询键随项目切换而变化', () => {
  const source = fs.readFileSync(path.join(__dirname, '../src/pages/UiPage.tsx'), 'utf8')
  assert.match(source, /queryKey: \['resources', targetScope, ctx\.projectId\]/)
  assert.match(source, /queryKey: \['suites', 'ui', ctx\.projectId\]/)
})

test('所有页面与组件里，queryFn 带 ctx.projectId 的查询必须把 projectId 放进键', () => {
  const offenders = []
  for (const file of sourceFiles()) {
    const problems = scopedKeyProblems(fs.readFileSync(file, 'utf8'), file)
    if (problems.length) offenders.push(`${path.basename(file)}: ${problems.join(' | ')}`)
  }
  assert.deepEqual(offenders, [], '以下查询键缺少 ctx.projectId：\n' + offenders.join('\n'))
})
