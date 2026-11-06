export const ONBOARDING_SKIP_KEY = 'testdock.onboarding.skipped'

export function validDisplayName(value: string): boolean {
  const length = Array.from(value.trim()).length
  return length >= 1 && length <= 60
}

export function displayName(value: string): string {
  if (!validDisplayName(value)) throw new Error('名称去除首尾空白后须为 1–60 字符')
  return value.trim()
}

export function onboardingDestination(complete: boolean, skipped: boolean): string {
  return complete || skipped ? '/overview' : '/onboarding'
}

export function onboardingSkipped(): boolean {
  try { return window.localStorage.getItem(ONBOARDING_SKIP_KEY) === '1' } catch { return false }
}
