/**
 * 从文本中提取手机号码
 * 支持中国大陆手机号格式 (11位，1开头)
 *
 * @param text 包含手机号的文本
 * @returns 提取到的手机号，如果没有找到返回空字符串
 */
export function extractPhoneNumber(text: string): string {
  if (!text || typeof text !== 'string') {
    return ''
  }

  // 匹配中国大陆手机号：1开头的11位数字
  // 支持常见格式：
  // - 纯数字：13812345678
  // - 带空格：138 1234 5678
  // - 带横杠：138-1234-5678
  const phoneRegex = /1[3-9]\d[\s\-]?\d{4}[\s\-]?\d{4}/g

  const matches = text.match(phoneRegex)

  if (matches && matches.length > 0) {
    // 移除空格和横杠，返回纯数字
    const cleanPhone = matches[0].replace(/[\s\-]/g, '')

    // 验证是否恰好是11位
    if (cleanPhone.length === 11) {
      return cleanPhone
    }
  }

  return ''
}

/**
 * 测试手机号提取功能
 */
export function testPhoneExtractor() {
  const testCases = [
    { input: '张三 13812345678 北京市朝阳区', expected: '13812345678' },
    { input: '李四，138-1234-5678，上海市浦东新区', expected: '13812345678' },
    { input: '王五 138 1234 5678 广州市天河区', expected: '13812345678' },
    { input: '收件人：赵六\n电话：15912345678\n地址：深圳市南山区', expected: '15912345678' },
    { input: '没有手机号的地址', expected: '' },
    { input: '座机：010-12345678', expected: '' }
  ]

  console.log('=== 手机号提取测试 ===')
  testCases.forEach((testCase, index) => {
    const result = extractPhoneNumber(testCase.input)
    const passed = result === testCase.expected
    console.log(`测试 ${index + 1}: ${passed ? '✓' : '✗'}`)
    console.log(`  输入: ${testCase.input}`)
    console.log(`  期望: ${testCase.expected}`)
    console.log(`  结果: ${result}`)
    console.log('')
  })
}
