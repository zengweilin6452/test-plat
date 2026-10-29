/**
 * 前端类型 ↔ 后端 OpenAPI 契约（工单 01）。
 *
 * 数据源：
 *   - docs/contracts/openapi.json（scripts/export_openapi.py 生成）
 *   - src/types.ts、src/api/types.ts（前端实际消费的类型）
 *
 * 规则（逐 schema）：
 *   1. OpenAPI 里声明的每个响应字段，前端接口必须声明；
 *   2. OpenAPI 标记 required 的字段，前端不能写成可选（`foo?`）；
 *   3. 前端多出来的字段只能是可选的（允许前端做防御性归一，但不许凭空发明必填字段）。
 *
 * 运行：npm test（CI 与本地同一条命令）。
 */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const ts = require('typescript')

const ROOT = path.resolve(__dirname, '..', '..')
const OPENAPI_PATH = path.join(ROOT, 'docs', 'contracts', 'openapi.json')
const TYPE_FILES = [
  path.join(__dirname, '..', 'src', 'types.ts'),
  path.join(__dirname, '..', 'src', 'api', 'types.ts'),
]

/** OpenAPI schema 名 -> 前端接口名 */
const MAPPING = {
  OverviewOut: 'OverviewSummary',
  ApplicationRecordOut: 'ApplicationRecord',
  ApplicationsOut: 'ApplicationsResponse',
  ResourceProfileOut: 'ResourceProfile',
  ResourceRecordOut: 'ResourceRecord',
  ResourcesOut: 'ResourcesResponse',
  ProjectRecordOut: 'ProjectRecord',
  ProjectsOut: 'ProjectsResponse',
  RunRecordOut: 'RunRecord',
  RunsOut: 'RunsResponse',
  TaskRecordOut: 'TaskRecord',
  TasksOut: 'TasksResponse',
  TaskRevisionRecord: 'TaskRevisionRecord',
  TaskRevisionListOut: 'TaskRevisionsResponse',
  ErrorEnvelope: 'ApiErrorEnvelope',
}

function parseInterfaces() {
  const interfaces = new Map()
  for (const file of TYPE_FILES) {
    const source = ts.createSourceFile(
      file,
      fs.readFileSync(file, 'utf8'),
      ts.ScriptTarget.Latest,
      true,
    )
    const visit = (node) => {
      if (ts.isInterfaceDeclaration(node)) {
        const props = new Map()
        for (const member of node.members) {
          if (!ts.isPropertySignature(member)) continue
          const name = member.name.getText(source)
          props.set(name, { optional: Boolean(member.questionToken) })
        }
        interfaces.set(node.name.text, props)
      }
      ts.forEachChild(node, visit)
    }
    visit(source)
  }
  return interfaces
}

function loadSchema(name) {
  const doc = JSON.parse(fs.readFileSync(OPENAPI_PATH, 'utf8'))
  const schema = doc.schemas && doc.schemas[name]
  assert.ok(schema, `OpenAPI 缺少 schema ${name}`)
  return schema
}

test('OpenAPI 基线与前端类型逐字段一致', () => {
  const interfaces = parseInterfaces()
  const problems = []

  for (const [schemaName, interfaceName] of Object.entries(MAPPING)) {
    const schema = loadSchema(schemaName)
    const props = schema.properties || {}
    const required = new Set(schema.required || [])
    const tsProps = interfaces.get(interfaceName)
    if (!tsProps) {
      problems.push(`${interfaceName}: 前端接口不存在（对应 ${schemaName}）`)
      continue
    }

    for (const [prop, _def] of Object.entries(props)) {
      if (!tsProps.has(prop)) {
        problems.push(`${interfaceName}.${prop}: OpenAPI 有、前端类型缺失`)
        continue
      }
      if (required.has(prop) && tsProps.get(prop).optional) {
        problems.push(`${interfaceName}.${prop}: OpenAPI 必填，前端却声明为可选`)
      }
    }

    for (const [prop, meta] of tsProps.entries()) {
      if (!(prop in props) && !meta.optional) {
        problems.push(`${interfaceName}.${prop}: 前端新增了必填字段，但 OpenAPI 没有`)
      }
    }
  }

  assert.deepEqual(problems, [], `契约不一致：\n  - ${problems.join('\n  - ')}`)
})
